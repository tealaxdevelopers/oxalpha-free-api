import hmac
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from config import CONFIG
from oxalpha_client import oxalpha_client
from tool_service import (
    format_tools_system_prompt,
    parse_all_tool_calls,
    build_openai_tool_calls,
)
from content_handler import process_messages_for_oxalpha
from file_store import file_store, public_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("oxalpha.server")

app = FastAPI(
    title="OxAlpha Free API",
    description="Full v1 OpenAI & Anthropic compatible LLM/Agent Proxy for OxAlpha.",
    version="1.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # wildcard origin + credentials is unsafe; Bearer tokens need no cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


import uuid as _uuid


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{_uuid.uuid4().hex[:16]}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    err_type = "invalid_request_error"
    if exc.status_code == 401:
        err_type = "authentication_error"
    elif exc.status_code == 403:
        err_type = "permission_error"
    elif exc.status_code == 404:
        err_type = "not_found_error"
    elif exc.status_code == 429:
        err_type = "rate_limit_error"
    elif exc.status_code >= 500:
        err_type = "api_error"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": str(exc.detail),
                "type": err_type,
                "param": None,
                "code": exc.status_code,
            }
        },
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    messages = []
    is_bad = False
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "")
        messages.append(f"{loc}: {msg}")
        if "not supported" in msg.lower():
            is_bad = True
    status_code = 400 if is_bad else 422
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": "; ".join(messages), "type": "invalid_request_error", "param": None, "code": status_code}},
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Internal server error", "type": "api_error", "param": None, "code": 500}},
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


def verify_api_key(request: Request):
    if not CONFIG.api_key:
        return None
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split("Bearer ", 1)[1].strip()
    elif request.headers.get("X-API-Key"):
        token = request.headers.get("X-API-Key").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    if not hmac.compare_digest(token.encode(), CONFIG.api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return token


def map_model_name(requested_model: str) -> str:
    # OxAlpha has a single upstream model; every requested alias routes to it.
    return CONFIG.default_model


# =========================================================================
#  HEALTH
# =========================================================================

@app.get("/")
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "OxAlpha Free API Proxy",
        "version": "1.3.0",
        "upstream": CONFIG.oxalpha_base_url,
        "default_model": CONFIG.default_model,
        "auto_continue": CONFIG.auto_continue,
        "turnstile_auto_solve": CONFIG.turnstile_auto_solve,
        "endpoints": [
            "/v1/chat/completions",
            "/v1/messages",
            "/v1/responses",
            "/v1/files",
            "/v1/models",
        ],
    }


@app.get("/v1/models")
async def list_models(auth=Depends(verify_api_key)):
    now = int(time.time())
    all_models = list(set(CONFIG.supported_models))
    return {
        "object": "list",
        "data": [
            {
                "id": m,
                "object": "model",
                "created": now,
                "owned_by": "oxalpha",
                "permission": [],
                "root": m,
                "parent": None,
            }
            for m in all_models
        ],
    }


@app.get("/v1/models/{model_id}")
async def retrieve_model(model_id: str, auth=Depends(verify_api_key)):
    now = int(time.time())
    all_models = list(set(CONFIG.supported_models))
    for m in all_models:
        if m.lower() == model_id.lower():
            return {
                "id": m,
                "object": "model",
                "created": now,
                "owned_by": "oxalpha",
                "permission": [],
                "root": m,
                "parent": None,
            }
    raise HTTPException(status_code=404, detail=f"The model '{model_id}' does not exist.")


# =========================================================================
#  FILES API
# =========================================================================

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@app.post("/v1/files")
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form("assistants"),
    auth=Depends(verify_api_key),
):
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
        filename = file.filename or "uploaded_file.txt"
        rec = file_store.save_file(filename, content, purpose)
        logger.info(f"File uploaded: {filename} ({len(content)} bytes) -> {rec['id']}")
        return public_record(rec)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload error: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")


@app.get("/v1/files")
async def list_files_endpoint(purpose: Optional[str] = None, auth=Depends(verify_api_key)):
    return {"object": "list", "data": file_store.list_files(purpose)}


@app.get("/v1/files/{file_id}")
async def get_file_endpoint(file_id: str, auth=Depends(verify_api_key)):
    rec = file_store.get_file(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    return public_record(rec)


@app.get("/v1/files/{file_id}/content")
async def get_file_content_endpoint(file_id: str, auth=Depends(verify_api_key)):
    data = file_store.get_file_content(file_id)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=data, media_type="application/octet-stream")


@app.delete("/v1/files/{file_id}")
async def delete_file_endpoint(file_id: str, auth=Depends(verify_api_key)):
    ok = file_store.delete_file(file_id)
    return {"id": file_id, "object": "file", "deleted": ok}


# =========================================================================
#  HELPERS
# =========================================================================

def _make_tools_prompt(tools: List[Dict[str, Any]]) -> str:
    if tools:
        return format_tools_system_prompt(tools)
    return (
        "[AGENT IDENTITY]\n"
        "You are an AUTONOMOUS AI AGENT. You have tool-use capability. "
        "Take action via tools, not just chat."
    )


def _indexed(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI streaming requires an `index` on every tool_calls delta entry."""
    return [{"index": i, **c} for i, c in enumerate(calls)]


def _token_count(text: str) -> int:
    return max(1, len(text) // 4)


# =========================================================================
#  OPENAI CHAT COMPLETIONS
# =========================================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, auth=Depends(verify_api_key)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    raw_messages = body.get("messages", [])
    if not raw_messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    requested_model = body.get("model", CONFIG.default_model)
    upstream_model = map_model_name(requested_model)
    stream = bool(body.get("stream", False))
    tools = body.get("tools", [])
    stream_options = body.get("stream_options") or {}
    include_usage = bool(stream_options.get("include_usage", False))

    tools_prompt = _make_tools_prompt(tools)
    processed = process_messages_for_oxalpha(raw_messages, tools_prompt=tools_prompt, tools=tools)

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created_time = int(time.time())

    # ---------- STREAMING ----------
    if stream:
        async def event_generator():
            full_content = ""
            full_reasoning = ""
            finish_reason = "stop"
            upstream_usage = None

            try:
                # Initial role delta (OpenAI convention)
                yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': requested_model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"

                async for event in oxalpha_client.chat_with_auto_continue(
                    messages=processed,
                    model=upstream_model,
                    auto_continue=CONFIG.auto_continue,
                    max_continuations=CONFIG.max_continuations,
                ):
                    if await request.is_disconnected():
                        logger.info("Client disconnected; aborting stream")
                        return

                    etype = event.get("type")

                    if etype == "reasoning":
                        delta = event.get("delta", "")
                        full_reasoning += delta
                        # Reasoning is accumulated but NOT streamed as a separate SSE
                        # delta, because non-standard delta keys (reasoning_content,
                        # reasoning) trigger "Invalid ... stream event" warnings in
                        # strict OpenAI-compatible clients such as OpenCode.

                    elif etype == "content":
                        delta = event.get("delta", "")
                        full_content += delta

                        # Only stream directly when no tools (we need to inspect full output for tool calls)
                        if not tools:
                            chunk = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": requested_model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": delta},
                                    "finish_reason": None,
                                }],
                            }
                            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                    elif etype == "finish":
                        finish_reason = event.get("finish_reason") or "stop"
                        if event.get("usage"):
                            upstream_usage = event["usage"]
                # --- Tool call detection (after full content accumulated) ---
                if tools and full_content:
                    parsed_calls, prose = parse_all_tool_calls(full_content, tools)
                    if parsed_calls:
                        # Emit prose first if any
                        if prose:
                            yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': requested_model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': prose}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"

                        # Emit all tool calls (OpenAI expects role-less tool_calls delta).
                        # content is explicitly null so strict clients don't complain about
                        # a missing field when switching from text to tool_calls.
                        yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': requested_model, 'choices': [{'index': 0, 'delta': {'tool_calls': _indexed(parsed_calls)}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
                        finish_reason = "tool_calls"
                    else:
                        # No tool call found — stream the buffered content
                        yield f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': requested_model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': full_content}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"

                # Final done chunk
                final_chunk = {'id': chat_id, 'object': 'chat.completion.chunk', 'created': created_time, 'model': requested_model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish_reason}]}
                if include_usage and upstream_usage:
                    pu = upstream_usage.get("prompt_tokens", 0) or upstream_usage.get("input_tokens", 0)
                    cu = upstream_usage.get("completion_tokens", 0) or upstream_usage.get("output_tokens", 0)
                    tu = upstream_usage.get("total_tokens", 0) or (pu + cu)
                    final_chunk['usage'] = {'prompt_tokens': pu, 'completion_tokens': cu, 'total_tokens': tu}
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # ---------- NON-STREAMING ----------
    full_content = ""
    full_reasoning = ""
    finish_reason = "stop"
    upstream_usage = None

    async for event in oxalpha_client.chat_with_auto_continue(
        messages=processed,
        model=upstream_model,
        auto_continue=CONFIG.auto_continue,
        max_continuations=CONFIG.max_continuations,
    ):
        if event.get("type") == "content":
            full_content += event.get("delta", "")
        elif event.get("type") == "reasoning":
            full_reasoning += event.get("delta", "")
        elif event.get("type") == "finish":
            finish_reason = event.get("finish_reason") or "stop"
            if event.get("usage"):
                upstream_usage = event["usage"]

    message: Dict[str, Any] = {"role": "assistant"}

    if tools:
        parsed_calls, prose = parse_all_tool_calls(full_content, tools)
        if parsed_calls:
            message["content"] = prose or None
            message["tool_calls"] = parsed_calls
            finish_reason = "tool_calls"
        else:
            message["content"] = full_content
    else:
        message["content"] = full_content

    if full_reasoning:
        message["reasoning_content"] = full_reasoning

    if upstream_usage:
        prompt_tokens = upstream_usage.get("prompt_tokens", 0) or upstream_usage.get("input_tokens", 0)
        completion_tokens = upstream_usage.get("completion_tokens", 0) or upstream_usage.get("output_tokens", 0)
        total_tokens = upstream_usage.get("total_tokens", 0) or (prompt_tokens + completion_tokens)
    else:
        prompt_tokens = sum(_token_count(str(m.get("content", ""))) for m in raw_messages)
        completion_tokens = _token_count(full_content + full_reasoning)
        total_tokens = prompt_tokens + completion_tokens

    return {
        "id": chat_id,
        "object": "chat.completion",
        "created": created_time,
        "model": requested_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }


# =========================================================================
#  ANTHROPIC MESSAGES API  (/v1/messages)
# =========================================================================

def _anthropic_to_openai_messages(raw_system: Any, raw_messages: List[Dict]) -> List[Dict]:
    """Convert Anthropic request format to internal OpenAI-like message list."""
    openai_messages: List[Dict[str, Any]] = []

    # System prompt (can be string or list of content blocks)
    if raw_system:
        if isinstance(raw_system, str):
            openai_messages.append({"role": "system", "content": raw_system})
        elif isinstance(raw_system, list):
            text = " ".join(
                p.get("text", "") for p in raw_system if isinstance(p, dict) and p.get("type") == "text"
            )
            if text:
                openai_messages.append({"role": "system", "content": text})

    for m in raw_messages:
        role = m.get("role")
        content = m.get("content")

        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")

                if ptype == "tool_use":
                    openai_messages.append({
                        "role": "assistant",
                        "tool_calls": [{
                            "id": part.get("id"),
                            "type": "function",
                            "function": {
                                "name": part.get("name"),
                                "arguments": json.dumps(part.get("input", {})),
                            },
                        }],
                    })
                elif ptype == "tool_result":
                    result_content = part.get("content", "")
                    if isinstance(result_content, list):
                        result_content = " ".join(
                            p.get("text", "") for p in result_content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": part.get("tool_use_id", ""),
                        "content": result_content,
                    })
                elif ptype == "text":
                    openai_messages.append({"role": role, "content": part.get("text", "")})
                elif ptype in ("image", "image_url"):
                    # Pass through image content blocks
                    openai_messages.append({"role": role, "content": [part]})
                else:
                    openai_messages.append({"role": role, "content": [part]})
        else:
            openai_messages.append({"role": role, "content": content})

    return openai_messages


@app.post("/v1/messages")
async def anthropic_messages(request: Request, auth=Depends(verify_api_key)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    raw_system = body.get("system", "")
    raw_messages = body.get("messages", [])
    requested_model = body.get("model", CONFIG.default_model)
    upstream_model = map_model_name(requested_model)
    stream = bool(body.get("stream", False))
    tools = body.get("tools", [])
    max_tokens = body.get("max_tokens", 8096)

    openai_messages = _anthropic_to_openai_messages(raw_system, raw_messages)
    tools_prompt = _make_tools_prompt(tools)
    processed = process_messages_for_oxalpha(openai_messages, tools_prompt=tools_prompt, tools=tools)

    msg_id = f"msg_{uuid.uuid4().hex[:20]}"

    # ---------- NON-STREAMING ----------
    if not stream:
        full_content = ""
        anthropic_usage = None
        async for event in oxalpha_client.chat_with_auto_continue(
            messages=processed,
            model=upstream_model,
            auto_continue=CONFIG.auto_continue,
            max_continuations=CONFIG.max_continuations,
        ):
            if event.get("type") == "content":
                full_content += event.get("delta", "")
            elif event.get("type") == "finish" and event.get("usage"):
                anthropic_usage = event["usage"]

        content_blocks = []
        stop_reason = "end_turn"

        if tools:
            parsed_calls, prose = parse_all_tool_calls(full_content, tools)
            if parsed_calls:
                if prose:
                    content_blocks.append({"type": "text", "text": prose})
                for tc in parsed_calls:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
                stop_reason = "tool_use"
            else:
                content_blocks.append({"type": "text", "text": full_content})
        else:
            content_blocks.append({"type": "text", "text": full_content})

        return {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": content_blocks,
            "model": requested_model,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": (anthropic_usage.get("prompt_tokens", 0) or anthropic_usage.get("input_tokens", 0)) if anthropic_usage else sum(_token_count(str(m.get("content", ""))) for m in raw_messages),
                "output_tokens": (anthropic_usage.get("completion_tokens", 0) or anthropic_usage.get("output_tokens", 0)) if anthropic_usage else _token_count(full_content),
            },
        }

    # ---------- STREAMING ----------
    async def anthropic_stream():
        full_content = ""

        yield (
            f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': requested_model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 1}}}, ensure_ascii=False)}\n\n"
        )

        # Open text block
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}, ensure_ascii=False)}\n\n"
        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"

        try:
            async for event in oxalpha_client.chat_with_auto_continue(
                messages=processed,
                model=upstream_model,
                auto_continue=CONFIG.auto_continue,
                max_continuations=CONFIG.max_continuations,
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected; aborting anthropic stream")
                    return
                if event.get("type") == "content":
                    delta = event.get("delta", "")
                    full_content += delta
                    # Stream text delta live
                    if not tools:
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': delta}}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Anthropic streaming error: {e}")

        # After full content is accumulated, resolve tool calls
        if tools:
            parsed_calls, prose = parse_all_tool_calls(full_content, tools)
            if parsed_calls:
                block_idx = 0
                if prose:
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': block_idx, 'delta': {'type': 'text_delta', 'text': prose}}, ensure_ascii=False)}\n\n"
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': block_idx})}\n\n"
                block_idx += 1

                for tc in parsed_calls:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}
                    call_id = tc.get("id", f"call_{uuid.uuid4().hex[:12]}")
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': block_idx, 'content_block': {'type': 'tool_use', 'id': call_id, 'name': fn.get('name', ''), 'input': {}}})}\n\n"
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': block_idx, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(args)}})}\n\n"
                    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': block_idx})}\n\n"
                    block_idx += 1

                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'tool_use', 'stop_sequence': None}, 'usage': {'output_tokens': _token_count(full_content)}})}\n\n"
            else:
                # No tool calls — emit text as single block
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': full_content}}, ensure_ascii=False)}\n\n"
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': _token_count(full_content)}})}\n\n"
        else:
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
            yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': _token_count(full_content)}})}\n\n"

        yield 'event: message_stop\ndata: {"type": "message_stop"}\n\n'

    return StreamingResponse(
        anthropic_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# =========================================================================
#  OPENAI RESPONSES API  (/v1/responses)
# =========================================================================

@app.post("/v1/responses")
async def responses_shim(request: Request, auth=Depends(verify_api_key)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    raw_input = body.get("input", "")
    messages: List[Dict[str, Any]] = []
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        messages = raw_input

    # Reuse chat completions logic
    fake_body = {
        "model": body.get("model", CONFIG.default_model),
        "messages": messages,
        "tools": body.get("tools", []),
        "stream": False,
    }

    class _FakeRequest:
        async def json(self_):
            return fake_body
        headers = request.headers

    comp = await chat_completions(_FakeRequest(), auth=auth)
    choice_msg = comp["choices"][0]["message"]

    output = []
    text = choice_msg.get("content") or ""
    if text:
        output.append({
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        })
    for tc in (choice_msg.get("tool_calls") or []):
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
         args = {}
        output.append({
            "type": "function_call",
            "id": tc.get("id"),
            "call_id": tc.get("id"),
            "name": fn.get("name", ""),
            "arguments": fn.get("arguments", "{}"),
        })
    if not output:
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": ""}]})

    return {
        "id": comp.get("id"),
        "object": "response",
        "created_at": comp.get("created"),
        "model": comp.get("model"),
        "output": output,
        "usage": comp.get("usage"),
        "status": "completed",
    }


# =========================================================================
#  MAIN
# =========================================================================

if __name__ == "__main__":
    import uvicorn
    import sys

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("=" * 60)
    print(f"[*] OxAlpha Free API Proxy v1.3.0")
    print(f"[*] Listening on http://{CONFIG.host}:{CONFIG.port}")
    print(f"[*] OpenAI Chat     : http://localhost:{CONFIG.port}/v1/chat/completions")
    print(f"[*] Anthropic       : http://localhost:{CONFIG.port}/v1/messages")
    print(f"[*] Files API       : http://localhost:{CONFIG.port}/v1/files")
    print(f"[*] Responses API   : http://localhost:{CONFIG.port}/v1/responses")
    print(f"[*] Models          : http://localhost:{CONFIG.port}/v1/models")
    print(f"[*] Turnstile       : {'Auto-solve ON' if CONFIG.turnstile_auto_solve else 'Disabled'}")
    print(f"[*] Auto-continue   : {'ON' if CONFIG.auto_continue else 'OFF'} (max {CONFIG.max_continuations} rounds)")
    print("=" * 60)

    uvicorn.run("server:app", host=CONFIG.host, port=CONFIG.port, reload=False)