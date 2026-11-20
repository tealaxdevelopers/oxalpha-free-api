import re
import json
import time
import logging
import asyncio
import random
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from config import CONFIG
from turnstile_service import get_turnstile_token
from sse import SSEParser

logger = logging.getLogger("oxalpha.client")

LENGTH_LIMIT_REGEX = re.compile(
    r"reached the length limit|length limit|достигл|límite de longitud|limite de longueur|Längenlimit|limite di lunghezza|长度上限|文字数の上限|길이 제한",
    re.IGNORECASE
)

class OxAlphaClient:
    def __init__(self, proxy: Optional[str] = CONFIG.proxy):
        self.base_url = CONFIG.oxalpha_base_url
        self.proxy = proxy
        self.csrf_token: Optional[str] = None
        self.cookies: Dict[str, str] = {}
        self.last_init_time: float = 0
        self._init_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(CONFIG.max_concurrent_requests)
        self._rate_timestamps: List[float] = []
        self._rate_lock = asyncio.Lock()
        
        # User-Agent matching modern Chrome
        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
    async def _ensure_session(self, force_refresh: bool = False):
        """Fetch fresh CSRF token and cookies from /chat page."""
        async with self._init_lock:
            now = time.time()
            if not force_refresh and self.csrf_token and (now - self.last_init_time < CONFIG.session_ttl_minutes * 60):
                return

            logger.info("Initializing Ox Alpha session (fetching CSRF token and cookies)...")
            last_exc = None
            for attempt in range(CONFIG.max_retries + 1):
                try:
                    async with httpx.AsyncClient(
                        proxy=self.proxy, 
                        headers=self.default_headers, 
                        timeout=httpx.Timeout(CONFIG.request_timeout, connect=CONFIG.connect_timeout), 
                        follow_redirects=True
                    ) as client:
                        resp = await client.get(f"{self.base_url}/chat")
                        if resp.status_code != 200:
                            raise RuntimeError(f"Failed to load Ox Alpha chat page: HTTP {resp.status_code}")
                        break
                except Exception as e:
                    last_exc = e
                    if attempt < CONFIG.max_retries:
                        await asyncio.sleep((CONFIG.backoff_factor * (2 ** attempt)) + 0.2)
                        continue
                    raise
            if last_exc and resp is None:
                raise last_exc

            # Extract CSRF token
            csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', resp.text)
            if not csrf_match:
                raise RuntimeError("CSRF token not found on Ox Alpha chat page")

            self.csrf_token = csrf_match.group(1)
            self.cookies = dict(resp.cookies)
            self.last_init_time = now
            logger.info(f"Ox Alpha session initialized successfully. CSRF: {self.csrf_token[:8]}...")

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        model: str = CONFIG.default_model,
        turnstile_token: Optional[str] = None,
        timeout: int = CONFIG.request_timeout,
        _turnstile_retry: bool = False,
        _skip_semaphore: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream chat completions from Ox Alpha /api/chat.
        Handles Turnstile 428 challenge automatically.
        Yields raw delta events from Ox Alpha stream.
        """
        _released = False
        if not _skip_semaphore:
            await self._semaphore.acquire()
        try:
            await self._ensure_session()
        except Exception:
            if not _skip_semaphore and not _released:
                try:
                    self._semaphore.release()
                except ValueError:
                    pass
                _released = True
            raise

        headers = {
            **self.default_headers,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": self.csrf_token,
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/chat",
        }
        if turnstile_token:
            headers["X-Turnstile-Token"] = turnstile_token
        # Drop any None-valued headers (defensive: httpx rejects None)
        headers = {k: v for k, v in headers.items() if v is not None}

        payload = {
            "model": model,
            "messages": messages
        }

        async with httpx.AsyncClient(
            proxy=self.proxy,
            cookies=self.cookies,
            timeout=httpx.Timeout(timeout, connect=CONFIG.connect_timeout),
            follow_redirects=True
        ) as client:
            resp = None
            TRANSIENT = {429, 502, 503, 504}
            for attempt in range(CONFIG.max_retries + 1):
                req = client.build_request("POST", f"{self.base_url}/api/chat", json=payload, headers=headers)
                try:
                    resp = await client.send(req, stream=True)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
                    if attempt < CONFIG.max_retries:
                        sleep = (CONFIG.backoff_factor * (2 ** attempt)) + random.uniform(0.1, 0.5)
                        logger.warning("Transient connection error %s (attempt %d/%d). Retrying in %.2fs", exc, attempt + 1, CONFIG.max_retries, sleep)
                        await asyncio.sleep(sleep)
                        continue
                    raise RuntimeError(f"Upstream network failure: {exc}")
                if resp.status_code in TRANSIENT and attempt < CONFIG.max_retries:
                    await resp.aclose()
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep = float(retry_after)
                    else:
                        sleep = (CONFIG.backoff_factor * (2 ** attempt)) + random.uniform(0.1, 0.5)
                    logger.warning("Transient HTTP %d (attempt %d/%d). Retrying in %.2fs", resp.status_code, attempt + 1, CONFIG.max_retries, sleep)
                    await asyncio.sleep(sleep)
                    continue
                break

            # Check if Cloudflare Turnstile verification is required (428)
            if resp.status_code == 419:
                await resp.aclose()
                logger.warning("CSRF token expired (HTTP 419). Refreshing session and retrying...")
                await self._ensure_session(force_refresh=True)
                headers["X-CSRF-TOKEN"] = self.csrf_token or ""
                if not _skip_semaphore and not _released:
                    self._semaphore.release()
                    _released = True
                async for chunk in self.stream_chat(
                    messages=messages,
                    model=model,
                    turnstile_token=turnstile_token,
                    timeout=timeout,
                    _turnstile_retry=_turnstile_retry,
                    _skip_semaphore=True,
                ):
                    yield chunk
                return

            if resp.status_code == 428:
                await resp.aclose()
                logger.warning("Cloudflare Turnstile checkpoint triggered (HTTP 428 turnstile_required)!")
                
                if _turnstile_retry:
                    raise HTTPException(status_code=429, detail="Turnstile token was rejected by Ox Alpha (HTTP 428 again).")

                if CONFIG.turnstile_auto_solve:
                    logger.info("Automatically solving Turnstile challenge...")
                    solved_token = await get_turnstile_token(force_refresh=True)
                    if solved_token:
                        logger.info("Retrying request with solved Turnstile token...")
                        if not _skip_semaphore and not _released:
                            self._semaphore.release()
                            _released = True
                        async for chunk in self.stream_chat(
                            messages=messages,
                            model=model,
                            turnstile_token=solved_token,
                            timeout=timeout,
                            _turnstile_retry=True,
                            _skip_semaphore=True,
                        ):
                            yield chunk
                        return
                    else:
                        raise HTTPException(status_code=429, detail="Failed to solve Cloudflare Turnstile token automatically.")
                else:
                    raise HTTPException(status_code=429, detail="Turnstile verification required (HTTP 428), but auto-solve is disabled.")

            # Check for other HTTP errors
            if resp.status_code != 200:
                body = await resp.aread()
                await resp.aclose()
                status = resp.status_code if resp.status_code in (400, 401, 403, 404, 422, 429) else 502
                raise HTTPException(status_code=status, detail=f"Ox Alpha returned error HTTP {resp.status_code}: {body.decode('utf-8', errors='ignore')}")

            # Stream SSE events (chunk-boundary / UTF-8 / CRLF / multi-line safe)
            parser = SSEParser()

            def _decode(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                payload = ev["data"].strip()
                if payload == "[DONE]":
                    return {"done": True}
                try:
                    data = json.loads(payload)
                except Exception:
                    logger.debug(f"Skipping non-JSON SSE payload: {payload[:120]!r}")
                    return None
                if isinstance(data, dict) and data.get("error") and not data.get("choices"):
                    err = data["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise RuntimeError(f"Ox Alpha stream error: {msg}")
                return {"data": data}

            try:
                async for raw_bytes in resp.aiter_bytes():
                    for ev in parser.feed(raw_bytes):
                        out = _decode(ev)
                        if out is None:
                            continue
                        yield out
                        if out.get("done"):
                            return
                for ev in parser.finish():
                    out = _decode(ev)
                    if out is not None:
                        yield out
                        if out.get("done"):
                            return
            finally:
                await resp.aclose()
                if not _skip_semaphore and not _released:
                    try:
                        self._semaphore.release()
                    except ValueError:
                        pass
                    _released = True

    async def chat_with_auto_continue(
        self,
        messages: List[Dict[str, Any]],
        model: str = CONFIG.default_model,
        auto_continue: bool = CONFIG.auto_continue,
        max_continuations: int = CONFIG.max_continuations
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Orchestrates streaming with auto-continuation:
        If generation stops or is truncated with length limit or cut off mid-code:
        Sends: 'Continue exactly from where you left off. Do not repeat anything.'
        Seamlessly continues yielding deltas!
        """
        working_messages = list(messages)
        rounds = 0
        total_content = ""
        total_reasoning = ""
        total_usage = None

        while True:
            round_content = ""
            round_reasoning = ""
            finish_reason = None
            is_cut_off = False

            round_usage = None
            async for event in self.stream_chat(working_messages, model=model):
                if event.get("done"):
                    break
                data = event.get("data", {})
                if isinstance(data.get("usage"), dict):
                    round_usage = data["usage"]
                choices = data.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})
                reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                content = delta.get("content") or ""
                finish_reason = choice.get("finish_reason") or finish_reason
                if isinstance(choice.get("usage"), dict):
                    round_usage = choice["usage"]

                if reasoning:
                    round_reasoning += reasoning
                    total_reasoning += reasoning
                    yield {"type": "reasoning", "delta": reasoning}

                if content:
                    round_content += content
                    total_content += content
                    yield {"type": "content", "delta": content}

            # Check if generation was cut off or hit length limit
            if finish_reason == "length":
                is_cut_off = True
            elif LENGTH_LIMIT_REGEX.search(round_content):
                is_cut_off = True
            # Also check if last block is an unclosed code block and response ended abruptly
            elif round_content.count("```") % 2 != 0 and len(round_content) > 3000:
                is_cut_off = True

            if round_usage:
                total_usage = round_usage

            # If not cut off, or auto-continue disabled, or max rounds reached, we finish
            if not is_cut_off or not auto_continue or rounds >= max_continuations:
                yield {
                    "type": "finish",
                    "finish_reason": finish_reason or "stop",
                    "full_content": total_content,
                    "full_reasoning": total_reasoning,
                    "usage": total_usage,
                }
                return

            # AUTO-CONTINUE TRIGGERED!
            rounds += 1
            logger.info(
                f"Generation cut off (round {rounds}/{max_continuations}). "
                f"Triggering auto-continuation with prompt: '{CONFIG.continuation_prompt}'"
            )

            # Clean any length limit notice text from the end before appending
            clean_round_content = LENGTH_LIMIT_REGEX.sub("", round_content).strip()

            # Append the assistant's partial reply and the continuation prompt
            working_messages.append({"role": "assistant", "content": clean_round_content})
            working_messages.append({"role": "user", "content": CONFIG.continuation_prompt})

            # Small delay before continuation to be gentle
            await asyncio.sleep(0.5)

oxalpha_client = OxAlphaClient()
