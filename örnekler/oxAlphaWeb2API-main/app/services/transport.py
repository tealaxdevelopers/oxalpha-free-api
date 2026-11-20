import asyncio
import logging
import random
from typing import Any, Callable, Dict, Optional
import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
)


class HTTPTransportPool:
    """Manages persistent httpx.AsyncClient with connection pooling, retries, and jitter."""

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings
        self._custom_client = client
        self._client: Optional[httpx.AsyncClient] = client

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=self.settings.max_concurrent_requests * 2,
                keepalive_expiry=30.0,
            )
            timeout = httpx.Timeout(
                timeout=self.settings.upstream_timeout_seconds,
                connect=self.settings.connect_timeout_seconds,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": self.settings.user_agent},
            )
        return self._client

    async def execute_with_retry(
        self,
        request_func: Callable[[httpx.AsyncClient], Any],
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None,
    ) -> httpx.Response:
        """Execute an HTTP request with exponential backoff and jitter on transient errors."""
        retries = max_retries if max_retries is not None else self.settings.max_retries
        factor = backoff_factor if backoff_factor is not None else self.settings.backoff_factor
        client = await self.get_client()

        attempt = 0
        while True:
            try:
                response: httpx.Response = await request_func(client)
                if response.status_code in TRANSIENT_STATUS_CODES and attempt < retries:
                    attempt += 1
                    # Check for Retry-After header
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = float(retry_after)
                    else:
                        sleep_time = (factor * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)

                    logger.warning(
                        "Transient HTTP status %d received (attempt %d/%d). Retrying in %.2fs",
                        response.status_code,
                        attempt,
                        retries,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                    continue

                return response

            except TRANSIENT_EXCEPTIONS as exc:
                if attempt < retries:
                    attempt += 1
                    sleep_time = (factor * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    logger.warning(
                        "Transient connection exception: %s (attempt %d/%d). Retrying in %.2fs",
                        str(exc),
                        attempt,
                        retries,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                logger.error("Exhausted retries on transient connection error: %s", exc)
                raise exc

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
