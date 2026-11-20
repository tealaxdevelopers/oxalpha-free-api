import json
import logging
from typing import AsyncGenerator
from fastapi import Request
from app.models.canonical import ChatResponseChunk
from app.models.openai import OpenAIChatCompletionChunk

logger = logging.getLogger(__name__)


def format_sse_chunk(chunk: ChatResponseChunk) -> str:
    """Format a canonical ChatResponseChunk into an OpenAI SSE string."""
    openai_chunk = OpenAIChatCompletionChunk.from_canonical(chunk)
    # Exclude None fields if needed, or serialize to JSON dict
    payload = openai_chunk.model_dump(exclude_none=True)
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def format_sse_done() -> str:
    """Return the terminal SSE done signal."""
    return "data: [DONE]\n\n"


async def sse_stream_generator(
    chunk_generator: AsyncGenerator[ChatResponseChunk, None],
    request: Request,
) -> AsyncGenerator[str, None]:
    """Wraps an async chunk generator and checks for client cancellation on each turn."""
    try:
        async for chunk in chunk_generator:
            if await request.is_disconnected():
                logger.info("Client disconnected. Aborting SSE stream.")
                break
            yield format_sse_chunk(chunk)
        yield format_sse_done()
    except Exception as exc:
        logger.error("Error during SSE stream: %s", exc)
        raise exc
