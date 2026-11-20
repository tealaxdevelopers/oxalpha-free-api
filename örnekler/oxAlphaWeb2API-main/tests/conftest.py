import json
import re
from typing import AsyncGenerator, Callable, Dict, Optional
import httpx
import pytest
from httpx import ASGITransport

from app.config import Settings
from app.main import create_app
from app.api.deps import set_global_provider
from app.providers.oxalpha import OxAlphaProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="csrf-token" content="mock-csrf-token-12345">
    <title>Chat with Ox Alpha</title>
</head>
<body>
    <div id="root"></div>
</body>
</html>
"""


class MockOxAlphaHandler:
    def __init__(self):
        self.call_count_get = 0
        self.call_count_post = 0
        self.post_status_code = 200
        self.custom_sse_chunks = None
        self.post_headers_received = {}
        self.post_body_received = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if request.method == "GET" and url_path == "/chat":
            self.call_count_get += 1
            headers = {
                "Content-Type": "text/html; charset=utf-8",
                "Set-Cookie": "ox_alpha_session=mock_session_cookie; Path=/; Secure; HttpOnly",
            }
            return httpx.Response(200, text=SAMPLE_HTML, headers=headers)

        elif request.method == "POST" and url_path == "/api/chat":
            self.call_count_post += 1
            self.post_headers_received = dict(request.headers)
            body_bytes = request.content
            try:
                self.post_body_received = json.loads(body_bytes.decode())
            except Exception:
                self.post_body_received = None

            if self.post_status_code != 200:
                return httpx.Response(self.post_status_code, json={"error": "Mocked upstream failure"})

            # Validate body
            if self.post_body_received:
                messages = self.post_body_received.get("messages", [])
                for m in messages:
                    if m.get("role") == "system":
                        return httpx.Response(422, json={"error": "Invalid messages"})

            if self.custom_sse_chunks is not None:
                content = "".join(self.custom_sse_chunks)
            else:
                chunk1 = json.dumps({
                    "id": "gen-mock-123",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "z-ai/glm-5.3-flash",
                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Hello! How can I assist you today?"}, "finish_reason": None}],
                })
                chunk2 = json.dumps({
                    "id": "gen-mock-123",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "z-ai/glm-5.3-flash",
                    "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
                })
                chunk3 = json.dumps({
                    "id": "gen-mock-123",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "z-ai/glm-5.3-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                })
                content = f"data: {chunk1}\n\ndata: {chunk2}\n\ndata: {chunk3}\n\ndata: [DONE]\n\n"

            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream; charset=utf-8"},
                text=content,
            )

        return httpx.Response(404, json={"error": "Not found"})


@pytest.fixture
def mock_handler():
    return MockOxAlphaHandler()


@pytest.fixture
def mock_transport(mock_handler):
    return httpx.MockTransport(mock_handler.handle)


@pytest.fixture
def test_settings():
    return Settings(
        api_keys=[],
        oxalpha_base_url="https://oxalpha.com",
        oxalpha_model="z-ai/glm-5.3-flash",
        gateway_model_name="oxalpha",
        upstream_timeout_seconds=5.0,
        max_concurrent_requests=10,
        rate_limit_per_minute=100,
        max_retries=2,
    )


@pytest.fixture
async def app_with_mock(test_settings, mock_transport):
    app = create_app()

    # Create mock httpx client with mock transport
    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=test_settings.oxalpha_base_url)
    transport_pool = HTTPTransportPool(test_settings, client=mock_client)
    rate_limiter = GatewayRateLimiter(max_concurrent=10, requests_per_minute=100)
    provider = OxAlphaProvider(
        settings=test_settings,
        transport=transport_pool,
        rate_limiter=rate_limiter,
    )

    set_global_provider(provider)
    app.state.transport = transport_pool
    app.state.provider = provider
    app.state.rate_limiter = rate_limiter

    yield app

    await mock_client.aclose()


@pytest.fixture
async def client(app_with_mock) -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = ASGITransport(app=app_with_mock)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
