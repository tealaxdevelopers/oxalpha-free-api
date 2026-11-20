from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from app.api.deps import get_provider, verify_api_key
from app.models.openai import (
    OpenAIChatCompletionRequest,
    OpenAIChatCompletionResponse,
)
from app.providers.base import AIProvider
from app.services.sse import sse_stream_generator

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.post(
    "/chat/completions",
    response_model=OpenAIChatCompletionResponse,
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/event-stream": {},
            },
            "description": "Standard OpenAI chat completion or SSE chunk stream",
        }
    },
)
async def create_chat_completion(
    request: Request,
    body: OpenAIChatCompletionRequest,
    provider: AIProvider = Depends(get_provider),
):
    """
    OpenAI-compatible Chat Completion endpoint supporting both
    standard JSON responses and Server-Sent Events (SSE) streaming.
    """
    canonical_req = body.to_canonical()

    if body.stream:
        return StreamingResponse(
            sse_stream_generator(provider.stream_chat(canonical_req), request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )

    response = await provider.chat(canonical_req)
    return OpenAIChatCompletionResponse.from_canonical(response)
