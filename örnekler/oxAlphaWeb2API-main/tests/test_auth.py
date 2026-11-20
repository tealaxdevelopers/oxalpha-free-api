import pytest
import httpx
from httpx import ASGITransport
from app.config import Settings, get_settings
from app.main import create_app
from app.api.deps import set_global_provider
from app.providers.oxalpha import OxAlphaProvider
from app.services.rate_limiter import GatewayRateLimiter
from app.services.transport import HTTPTransportPool


@pytest.mark.asyncio
async def test_auth_bypass_when_empty_api_keys(mock_transport):
    """When API_KEYS is empty, requests should proceed without credentials."""
    settings = Settings(api_keys=[], oxalpha_base_url="https://oxalpha.com")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=settings.oxalpha_base_url)
    transport = HTTPTransportPool(settings, client=mock_client)
    provider = OxAlphaProvider(settings, transport, GatewayRateLimiter(10, 100))
    set_global_provider(provider)

    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    resp = await client.get("/v1/models")
    assert resp.status_code == 200

    await mock_client.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_enforcement_with_configured_keys(mock_transport):
    """When API_KEYS is set, missing or wrong keys must yield 401."""
    valid_key = "sk-test-secret-key-123"
    settings = Settings(api_keys=[valid_key], oxalpha_base_url="https://oxalpha.com")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    mock_client = httpx.AsyncClient(transport=mock_transport, base_url=settings.oxalpha_base_url)
    transport = HTTPTransportPool(settings, client=mock_client)
    provider = OxAlphaProvider(settings, transport, GatewayRateLimiter(10, 100))
    set_global_provider(provider)

    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    # 1. No auth provided -> 401
    resp_no_auth = await client.get("/v1/models")
    assert resp_no_auth.status_code == 401
    data = resp_no_auth.json()
    assert data["error"]["type"] == "authentication_error"

    # 2. Invalid Bearer token -> 401
    resp_bad_auth = await client.get(
        "/v1/models", headers={"Authorization": "Bearer invalid-token"}
    )
    assert resp_bad_auth.status_code == 401

    # 3. Valid Bearer token -> 200
    resp_valid_bearer = await client.get(
        "/v1/models", headers={"Authorization": f"Bearer {valid_key}"}
    )
    assert resp_valid_bearer.status_code == 200

    # 4. Valid X-API-Key header -> 200
    resp_valid_header = await client.get(
        "/v1/models", headers={"X-API-Key": valid_key}
    )
    assert resp_valid_header.status_code == 200

    await mock_client.aclose()
    await client.aclose()
