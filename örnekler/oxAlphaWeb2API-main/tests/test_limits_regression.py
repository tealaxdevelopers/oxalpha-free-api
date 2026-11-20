import asyncio
import time
import httpx
import pytest
from httpx import ASGITransport

from app.config import Settings
from app.main import create_app
from app.api.deps import set_global_provider
from app.models.canonical import ChatMessage, ChatRequest
from app.providers.oxalpha import OxAlphaProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool


@pytest.mark.asyncio
async def test_concurrency_semaphore_limits():
    """Verify that GatewayRateLimiter strictly enforces max concurrency."""
    max_concurrent = 3
    limiter = GatewayRateLimiter(max_concurrent=max_concurrent, requests_per_minute=100)

    active_tasks = 0
    max_observed_active = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal active_tasks, max_observed_active
        async with limiter.limit(timeout=5.0):
            async with lock:
                active_tasks += 1
                if active_tasks > max_observed_active:
                    max_observed_active = active_tasks
            await asyncio.sleep(0.05)
            async with lock:
                active_tasks -= 1

    # Launch 10 simultaneous workers
    tasks = [asyncio.create_task(worker()) for _ in range(10)]
    await asyncio.gather(*tasks)

    # Concurrency should never have exceeded max_concurrent
    assert max_observed_active <= max_concurrent
    assert limiter.semaphore._value == max_concurrent


@pytest.mark.asyncio
async def test_sliding_window_burst_smoothing():
    """Verify that requests exceeding the per-minute limit are smoothed rather than failing."""
    rpm = 5
    limiter = GatewayRateLimiter(max_concurrent=10, requests_per_minute=rpm)
    limiter.window_seconds = 0.5  # Shrink window for fast test execution

    timestamps = []

    async def worker():
        async with limiter.limit(timeout=2.0):
            timestamps.append(time.monotonic())

    # Send 7 requests (2 more than the 5 RPM limit)
    start_time = time.monotonic()
    tasks = [asyncio.create_task(worker()) for _ in range(7)]
    await asyncio.gather(*tasks)
    total_duration = time.monotonic() - start_time

    assert len(timestamps) == 7
    # 6th and 7th requests must have waited for the window to slide
    assert total_duration >= 0.4


@pytest.mark.asyncio
async def test_rate_limiter_timeout_on_starvation():
    """Verify that if wait time exceeds the timeout, a TimeoutError is raised."""
    limiter = GatewayRateLimiter(max_concurrent=1, requests_per_minute=1)
    limiter.window_seconds = 10.0

    async def task_holder():
        async with limiter.limit(timeout=1.0):
            await asyncio.sleep(0.5)

    holder = asyncio.create_task(task_holder())
    await asyncio.sleep(0.05)

    # Second request with short timeout should time out
    with pytest.raises(TimeoutError):
        async with limiter.limit(timeout=0.1):
            pass

    await holder


@pytest.mark.asyncio
async def test_upstream_429_exponential_backoff_retry():
    """Verify that the transport pool automatically retries on HTTP 429 with backoff."""
    attempt_count = 0

    def mock_429_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": "Rate limit exceeded, please back off."}
            )
        return httpx.Response(200, json={"status": "recovered"})

    settings = Settings(max_retries=3, backoff_factor=0.01)
    mock_client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_429_handler),
        base_url="http://test"
    )
    transport_pool = HTTPTransportPool(settings, client=mock_client)

    async def do_call(c: httpx.AsyncClient):
        return await c.get("http://test/retry-429")

    response = await transport_pool.execute_with_retry(do_call)
    assert response.status_code == 200
    assert attempt_count == 3
    await mock_client.aclose()


@pytest.mark.asyncio
async def test_large_context_normalization():
    """Verify that large prompts (e.g. 10,000 words) are normalized without crashing."""
    settings = Settings(oxalpha_base_url="https://oxalpha.com")
    transport = HTTPTransportPool(settings)
    provider = OxAlphaProvider(settings, transport)

    large_content = "This is a detailed analysis word " * 1000  # ~33k characters
    messages = [
        ChatMessage(role="system", content="System instruction for large payload."),
        ChatMessage(role="user", content=large_content),
    ]

    normalized = provider._normalize_messages(messages)
    assert len(normalized) == 1
    assert normalized[0]["role"] == "user"
    assert "[System Instruction:" in normalized[0]["content"]
    assert len(normalized[0]["content"]) > 30000
