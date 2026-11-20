import logging
from typing import Optional
from fastapi import Header, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.providers.base import AIProvider

logger = logging.getLogger(__name__)

security_bearer = HTTPBearer(auto_error=False)

# Global provider instance placeholder, initialized during app lifespan
_provider_instance: Optional[AIProvider] = None


def set_global_provider(provider: AIProvider) -> None:
    global _provider_instance
    _provider_instance = provider


def get_provider() -> AIProvider:
    if _provider_instance is None:
        raise RuntimeError("Provider has not been initialized.")
    return _provider_instance


async def verify_api_key(
    bearer_auth: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    settings: Settings = Security(get_settings),
) -> Optional[str]:
    """
    Validate client API Key via Bearer token or X-API-Key header.
    If settings.api_keys is empty, bypass authentication (dev mode).
    """
    if not settings.api_keys:
        # Dev bypass mode
        return None

    client_key: Optional[str] = None
    if bearer_auth and bearer_auth.credentials:
        client_key = bearer_auth.credentials
    elif x_api_key:
        client_key = x_api_key

    if not client_key or client_key not in settings.api_keys:
        logger.warning("Unauthorized access attempt. Provided key invalid or missing.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect API key provided. You must provide a valid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return client_key
