import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.config import Settings
from app.models.canonical import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatResponseChoice,
    ChatResponseChunk,
    ChatChunkChoice,
    ChatChunkDelta,
    ModelCard,
    ModelList,
    UsageInfo,
)
from app.providers.base import AIProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool

logger = logging.getLogger(__name__)


class OxAlphaProvider(AIProvider):
    """Clean-room provider adapter for the OxAlpha web chat interface."""

    def __init__(
        self,
        settings: Settings,
        transport: HTTPTransportPool,
        rate_limiter: Optional[GatewayRateLimiter] = None,
    ):
        self.settings = settings
        self.transport = transport
        self.rate_limiter = rate_limiter or GatewayRateLimiter(
            max_concurrent=settings.max_concurrent_requests,
            requests_per_minute=settings.rate_limit_per_minute,
        )

        self._csrf_token: Optional[str] = None
        self._cookies: Dict[str, str] = {}
        self._session_created_at: float = 0.0
        self._session_ttl_seconds: float = 3600.0  # Session lasts 2 hours, refresh after 1 hour
        self._session_lock = asyncio.Lock()

    async def _get_or_refresh_session(self, force_refresh: bool = False) -> None:
        """Fetch or refresh the CSRF token and guest session cookies."""
        async with self._session_lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._csrf_token
                and self._cookies
                and (now - self._session_created_at < self._session_ttl_seconds)
            ):
                return

            client = await self.transport.get_client()
            url = f"{self.settings.oxalpha_base_url.rstrip('/')}/chat"

            async def _fetch_page(c: httpx.AsyncClient) -> httpx.Response:
                return await c.get(
                    url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )

            logger.info("Initializing/refreshing OxAlpha session from %s", url)
            response = await self.transport.execute_with_retry(_fetch_page)
            if response.status_code != 200:
                logger.error("Failed to fetch OxAlpha session page: HTTP %d", response.status_code)
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to initialize upstream session: HTTP {response.status_code}",
                )

            html = response.text
            csrf_match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
            if not csrf_match:
                logger.error("Could not find csrf-token meta tag in OxAlpha page HTML.")
                raise HTTPException(
                    status_code=502,
                    detail="Upstream protocol error: Missing CSRF token in page HTML",
                )

            self._csrf_token = csrf_match.group(1)
            # Store cookies from response
            self._cookies = dict(response.cookies)
            self._session_created_at = now
            logger.info("OxAlpha session established successfully. CSRF token acquired.")

    def _normalize_messages(self, messages: List[ChatMessage]) -> List[Dict[str, str]]:
        """
        Normalize messages to OxAlpha's strictly required schema.
        OxAlpha strictly rejects 'system' messages with HTTP 422 {"error": "Invalid messages"}.
        System instructions are folded into user messages.
        """
        if not messages:
            return [{"role": "user", "content": "Hello"}]

        system_prompts: List[str] = []
        conversation: List[Dict[str, str]] = []

        for msg in messages:
            role = msg.role.lower()
            if role == "system":
                system_prompts.append(msg.content.strip())
            elif role in ("user", "assistant"):
                conversation.append({"role": role, "content": msg.content})
            else:
                # Default unknown roles to user
                conversation.append({"role": "user", "content": msg.content})

        # If system instructions exist, prepend them to the first user message
        if system_prompts:
            combined_system = "\n\n".join(f"[System Instruction: {sp}]" for sp in system_prompts)
            if conversation:
                # Find first user message
                first_user_idx = None
                for idx, m in enumerate(conversation):
                    if m["role"] == "user":
                        first_user_idx = idx
                        break

                if first_user_idx is not None:
                    conversation[first_user_idx]["content"] = (
                        f"{combined_system}\n\n{conversation[first_user_idx]['content']}"
                    )
                else:
                    conversation.insert(0, {"role": "user", "content": combined_system})
            else:
                conversation.append({"role": "user", "content": combined_system})

        return conversation

    def _map_model(self, requested_model: str) -> str:
        """Map client model identifier to upstream supported model."""
        requested = (requested_model or "").strip().lower()
        if requested in (self.settings.gateway_model_name, "ox-alpha", "oxalpha", "default"):
            return self.settings.oxalpha_model
        # Allow exact upstream model identifier if provided directly
        if requested == self.settings.oxalpha_model.lower():
            return self.settings.oxalpha_model
        # Default fallback to configured upstream model
        logger.debug("Mapping requested model '%s' to '%s'", requested_model, self.settings.oxalpha_model)
        return self.settings.oxalpha_model

    async def list_models(self) -> ModelList:
        """Return canonical list of supported models."""
        now = 1700000000
        return ModelList(
            object="list",
            data=[
                ModelCard(id="oxalpha", object="model", created=now, owned_by="oxalpha"),
                ModelCard(id="ox-alpha", object="model", created=now, owned_by="oxalpha"),
                ModelCard(id="z-ai/glm-5.3-flash", object="model", created=now, owned_by="oxalpha"),
            ],
        )

    async def stream_chat(
        self, request: ChatRequest
    ) -> AsyncGenerator[ChatResponseChunk, None]:
        """Stream chat completion chunks via SSE."""
        await self._get_or_refresh_session()

        payload = {
            "model": self._map_model(request.model),
            "messages": self._normalize_messages(request.messages),
        }

        url = f"{self.settings.oxalpha_base_url.rstrip('/')}/api/chat"
        client = await self.transport.get_client()

        chatcmpl_id = f"chatcmpl-oxalpha-{uuid4().hex[:12]}"
        created_ts = int(time.time())

        # Enforce rate limiting and concurrency
        async with self.rate_limiter.limit():
            headers = {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-CSRF-TOKEN": self._csrf_token or "",
                "Origin": self.settings.oxalpha_base_url,
                "Referer": f"{self.settings.oxalpha_base_url.rstrip('/')}/chat",
            }
            if self.settings.oxalpha_turnstile_token:
                headers["X-Turnstile-Token"] = self.settings.oxalpha_turnstile_token

            # Attempt stream request, refreshing session once on 419 CSRF mismatch
            for attempt in range(2):
                try:
                    req = client.build_request("POST", url, json=payload, headers=headers, cookies=self._cookies)
                    response = await client.send(req, stream=True)

                    if response.status_code == 419 and attempt == 0:
                        logger.warning("CSRF token expired (HTTP 419). Refreshing session and retrying...")
                        await response.aclose()
                        await self._get_or_refresh_session(force_refresh=True)
                        headers["X-CSRF-TOKEN"] = self._csrf_token or ""
                        continue

                    if response.status_code == 428:
                        error_body = await response.aread()
                        await response.aclose()
                        err_text = error_body.decode(errors="ignore")
                        logger.warning("OxAlpha guest checkpoint limit reached (HTTP 428 Turnstile Required): %s", err_text)
                        raise HTTPException(
                            status_code=429,
                            detail="OxAlpha guest limit reached (20 free messages per checkpoint). Cloudflare verification required upstream.",
                        )

                    if response.status_code == 429:
                        error_body = await response.aread()
                        await response.aclose()
                        logger.warning("OxAlpha upstream rate limit (429): %s", error_body.decode(errors="ignore"))
                        raise HTTPException(status_code=429, detail="Upstream rate limit exceeded. Please retry later.")

                    if response.status_code != 200:
                        error_body = await response.aread()
                        await response.aclose()
                        error_msg = error_body.decode(errors="ignore")
                        logger.error("OxAlpha upstream error (HTTP %d): %s", response.status_code, error_msg)
                        raise HTTPException(
                            status_code=response.status_code if response.status_code in (400, 422) else 502,
                            detail=f"Upstream OxAlpha error: {error_msg}",
                        )

                    # Stream response lines
                    current_event = ""
                    first_chunk = True

                    try:
                        async for raw_line in response.aiter_lines():
                            line = raw_line.strip()
                            if not line:
                                current_event = ""
                                continue

                            if line.startswith("event:"):
                                current_event = line[6:].strip()
                                continue

                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    break

                                if current_event == "error":
                                    try:
                                        err_obj = json.loads(data_str)
                                        err_msg = err_obj.get("error", "Stream error from upstream")
                                    except Exception:
                                        err_msg = data_str
                                    raise HTTPException(status_code=502, detail=f"Upstream stream error: {err_msg}")

                                try:
                                    parsed = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue

                                # Yield initial role chunk if first turn
                                if first_chunk:
                                    first_chunk = False
                                    yield ChatResponseChunk(
                                        id=chatcmpl_id,
                                        object="chat.completion.chunk",
                                        created=created_ts,
                                        model=request.model,
                                        choices=[
                                            ChatChunkChoice(
                                                index=0,
                                                delta=ChatChunkDelta(role="assistant", content=""),
                                                finish_reason=None,
                                            )
                                        ],
                                    )

                                # Extract choices delta and usage
                                choices = parsed.get("choices", [])
                                content = ""
                                finish_reason = None

                                if choices:
                                    choice = choices[0]
                                    delta = choice.get("delta", {})
                                    content = delta.get("content", "")
                                    finish_reason = choice.get("finish_reason")

                                usage_info = None
                                if "usage" in parsed and parsed["usage"]:
                                    u = parsed["usage"]
                                    usage_info = UsageInfo(
                                        prompt_tokens=u.get("prompt_tokens", 0),
                                        completion_tokens=u.get("completion_tokens", 0),
                                        total_tokens=u.get("total_tokens", 0),
                                    )

                                if content or finish_reason or usage_info:
                                    yield ChatResponseChunk(
                                        id=chatcmpl_id,
                                        object="chat.completion.chunk",
                                        created=created_ts,
                                        model=request.model,
                                        choices=[
                                            ChatChunkChoice(
                                                index=0,
                                                delta=ChatChunkDelta(content=content),
                                                finish_reason=finish_reason,
                                            )
                                        ],
                                        usage=usage_info,
                                    )

                    finally:
                        await response.aclose()

                    return

                except httpx.RequestError as exc:
                    if attempt == 0:
                        logger.warning("Request error on attempt %d: %s. Retrying...", attempt + 1, exc)
                        await asyncio.sleep(0.5)
                        continue
                    raise HTTPException(status_code=502, detail=f"Upstream network failure: {exc}")

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute a non-streaming chat completion by aggregating the upstream stream."""
        content_parts: List[str] = []
        finish_reason: str = "stop"
        usage: UsageInfo = UsageInfo(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        chatcmpl_id = f"chatcmpl-oxalpha-{uuid4().hex[:12]}"
        created_ts = int(time.time())

        async for chunk in self.stream_chat(request):
            chatcmpl_id = chunk.id
            created_ts = chunk.created
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices:
                if choice.delta and choice.delta.content:
                    content_parts.append(choice.delta.content)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        full_content = "".join(content_parts)
        return ChatResponse(
            id=chatcmpl_id,
            object="chat.completion",
            created=created_ts,
            model=request.model,
            choices=[
                ChatResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=full_content),
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
        )

    async def health_check(self) -> bool:
        """Verify provider availability."""
        try:
            await self._get_or_refresh_session()
            return bool(self._csrf_token)
        except Exception as exc:
            logger.warning("Health check failed: %s", exc)
            return False
