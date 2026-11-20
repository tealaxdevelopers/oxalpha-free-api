import pytest
import httpx


@pytest.mark.asyncio
async def test_health_endpoint(client: httpx.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root_endpoint(client: httpx.AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert "version" in data


@pytest.mark.asyncio
async def test_chat_completion_non_streaming(client: httpx.AsyncClient):
    payload = {
        "model": "oxalpha",
        "messages": [
            {"role": "user", "content": "Hello! How can I assist you today?"}
        ],
        "stream": False,
        "temperature": 0.7,
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "chat.completion"
    assert data["model"] == "oxalpha"
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "Hello! How can I assist you today?"
    assert choice["finish_reason"] == "stop"

    # Verify usage exists
    assert "usage" in data
    assert data["usage"]["prompt_tokens"] == 12
    assert data["usage"]["completion_tokens"] == 8
    assert data["usage"]["total_tokens"] == 20


@pytest.mark.asyncio
async def test_chat_completion_system_folding(client: httpx.AsyncClient, mock_handler):
    payload = {
        "model": "oxalpha",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "What is 2+2?"}
        ],
        "stream": False,
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200

    # Ensure upstream did NOT receive system role (which causes 422)
    upstream_body = mock_handler.post_body_received
    assert upstream_body is not None
    for msg in upstream_body["messages"]:
        assert msg["role"] != "system"
        assert msg["role"] in ("user", "assistant")

    # Verify system message was merged into user message
    assert "[System Instruction: Be concise.]" in upstream_body["messages"][0]["content"]


@pytest.mark.asyncio
async def test_unsupported_tools_parameter_returns_400(client: httpx.AsyncClient):
    payload = {
        "model": "oxalpha",
        "messages": [{"role": "user", "content": "What's the weather?"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                },
            }
        ],
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "invalid_request_error"
    assert "not supported" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_unsupported_functions_parameter_returns_400(client: httpx.AsyncClient):
    payload = {
        "model": "oxalpha",
        "messages": [{"role": "user", "content": "What's the weather?"}],
        "functions": [{"name": "test_fn"}],
    }
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data
    assert "not supported" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_request_id_propagation(client: httpx.AsyncClient):
    # Test client-provided request ID
    custom_req_id = "custom-trace-id-12345"
    resp = await client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == custom_req_id

    # Test auto-generated request ID
    resp2 = await client.get("/health")
    assert resp2.status_code == 200
    generated_id = resp2.headers.get("X-Request-ID")
    assert generated_id is not None
    assert generated_id.startswith("req_")
