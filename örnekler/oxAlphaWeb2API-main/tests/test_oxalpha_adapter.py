import pytest
import httpx
from fastapi import HTTPException
from app.config import Settings
from app.models.canonical import ChatMessage, ChatRequest
from app.providers.oxalpha import OxAlphaProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool


def test_normalize_messages_system_folding():
    settings = Settings(oxalpha_base_url="https://oxalpha.com")
    transport = HTTPTransportPool(settings)
    provider = OxAlphaProvider(settings, transport)

    messages = [
        ChatMessage(role="system", content="You are a senior developer."),
        ChatMessage(role="user", content="Explain recursion."),
    ]
    normalized = provider._normalize_messages(messages)
    assert len(normalized) == 1
    assert normalized[0]["role"] == "user"
    assert "[System Instruction: You are a senior developer.]" in normalized[0]["content"]
    assert "Explain recursion." in normalized[0]["content"]


def test_normalize_messages_multiturn():
    settings = Settings(oxalpha_base_url="https://oxalpha.com")
    transport = HTTPTransportPool(settings)
    provider = OxAlphaProvider(settings, transport)

    messages = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="Hello!"),
        ChatMessage(role="user", content="How are you?"),
    ]
    normalized = provider._normalize_messages(messages)
    assert len(normalized) == 3
    assert normalized[0] == {"role": "user", "content": "Hi"}
    assert normalized[1] == {"role": "assistant", "content": "Hello!"}
    assert normalized[2] == {"role": "user", "content": "How are you?"}


def test_model_mapping():
    settings = Settings(oxalpha_model="z-ai/glm-5.3-flash")
    transport = HTTPTransportPool(settings)
    provider = OxAlphaProvider(settings, transport)

    assert provider._map_model("oxalpha") == "z-ai/glm-5.3-flash"
    assert provider._map_model("ox-alpha") == "z-ai/glm-5.3-flash"
    assert provider._map_model("z-ai/glm-5.3-flash") == "z-ai/glm-5.3-flash"
    assert provider._map_model("unknown-custom") == "z-ai/glm-5.3-flash"


@pytest.mark.asyncio
async def test_session_init_and_health_check(mock_transport, test_settings):
    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=test_settings.oxalpha_base_url)
    transport = HTTPTransportPool(test_settings, client=mock_client)
    provider = OxAlphaProvider(test_settings, transport)

    is_healthy = await provider.health_check()
    assert is_healthy is True
    assert provider._csrf_token == "mock-csrf-token-12345"

    await mock_client.aclose()


@pytest.mark.asyncio
async def test_upstream_429_handling(mock_handler, test_settings):
    mock_handler.post_status_code = 429
    mock_transport = httpx.MockTransport(mock_handler.handle)
    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=test_settings.oxalpha_base_url)
    transport = HTTPTransportPool(test_settings, client=mock_client)
    provider = OxAlphaProvider(test_settings, transport)

    req = ChatRequest(model="oxalpha", messages=[ChatMessage(role="user", content="Hello")])

    with pytest.raises(HTTPException) as exc_info:
        await provider.chat(req)

    assert exc_info.value.status_code == 429
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_upstream_428_turnstile_required_handling(mock_handler, test_settings):
    mock_handler.post_status_code = 428
    mock_transport = httpx.MockTransport(mock_handler.handle)
    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=test_settings.oxalpha_base_url)
    transport = HTTPTransportPool(test_settings, client=mock_client)
    provider = OxAlphaProvider(test_settings, transport)

    req = ChatRequest(model="oxalpha", messages=[ChatMessage(role="user", content="Hello")])

    with pytest.raises(HTTPException) as exc_info:
        await provider.chat(req)

    assert exc_info.value.status_code == 429
    assert "Cloudflare verification" in exc_info.value.detail
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_retry_on_transient_failure():
    """Verify transport pool executes retries on transient errors."""
    attempts = 0

    def transient_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, text="Success")

    mock_tr = httpx.MockTransport(transient_handler)
    settings = Settings(max_retries=2, backoff_factor=0.01)
    mock_client = httpx.AsyncClient(transport=mock_tr, base_url="http://test")
    pool = HTTPTransportPool(settings, client=mock_client)

    async def do_req(c: httpx.AsyncClient):
        return await c.get("http://test/retry-test")

    resp = await pool.execute_with_retry(do_req)
    assert resp.status_code == 200
    assert attempts == 2

    await mock_client.aclose()
