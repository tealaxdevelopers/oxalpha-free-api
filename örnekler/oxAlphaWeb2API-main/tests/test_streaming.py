import json
import pytest
import httpx
from starlette.requests import Request
from app.models.canonical import ChatChunkChoice, ChatChunkDelta, ChatResponseChunk
from app.services.sse import format_sse_chunk, format_sse_done, sse_stream_generator


@pytest.mark.asyncio
async def test_streaming_chat_completion(client: httpx.AsyncClient):
    payload = {
        "model": "oxalpha",
        "messages": [
            {"role": "user", "content": "Tell me a joke."}
        ],
        "stream": True,
    }
    response = await client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["Content-Type"]

    raw_text = response.text
    lines = raw_text.strip().split("\n\n")

    chunks = []
    received_done = False

    for block in lines:
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line == "data: [DONE]":
                received_done = True
                continue
            if line.startswith("data: "):
                data_json = json.loads(line[6:])
                chunks.append(data_json)

    assert received_done is True
    assert len(chunks) >= 2

    # Check first chunk has role
    first_choice = chunks[0]["choices"][0]
    assert first_choice["delta"].get("role") == "assistant"

    # Check id format
    assert chunks[0]["id"].startswith("chatcmpl-oxalpha-")
    assert chunks[0]["object"] == "chat.completion.chunk"

    # Check content chunks
    contents = [c["choices"][0]["delta"].get("content", "") for c in chunks if "content" in c["choices"][0]["delta"]]
    full_text = "".join(contents)
    assert "Hello! How can I assist you today?" in full_text


@pytest.mark.asyncio
async def test_client_disconnect_aborts_stream():
    """Verify that if the client disconnects, the sse_stream_generator halts immediately."""
    async def sample_generator():
        for i in range(10):
            yield ChatResponseChunk(
                id="test",
                object="chat.completion.chunk",
                created=1700000000,
                model="oxalpha",
                choices=[ChatChunkChoice(index=0, delta=ChatChunkDelta(content=f"word {i}"), finish_reason=None)],
            )

    # Mock request where is_disconnected returns True on second turn
    call_count = 0

    class MockDisconnectRequest:
        async def is_disconnected(self):
            nonlocal call_count
            call_count += 1
            return call_count > 2

    results = []
    async for item in sse_stream_generator(sample_generator(), MockDisconnectRequest()):
        results.append(item)

    # Generator should have stopped after 2 iterations + 1 done signal
    assert len(results) <= 4
    assert any("[DONE]" in r for r in results)


def test_sse_formatting():
    chunk = ChatResponseChunk(
        id="chatcmpl-123",
        object="chat.completion.chunk",
        created=1700000000,
        model="oxalpha",
        choices=[
            ChatChunkChoice(
                index=0,
                delta=ChatChunkDelta(role="assistant", content="Hi"),
                finish_reason=None,
            )
        ],
    )
    formatted = format_sse_chunk(chunk)
    assert formatted.startswith("data: {")
    assert formatted.endswith("\n\n")
    assert '"role":"assistant"' in formatted
    assert '"content":"Hi"' in formatted

    done = format_sse_done()
    assert done == "data: [DONE]\n\n"
