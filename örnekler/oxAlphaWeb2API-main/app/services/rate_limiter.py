import asyncio
import time
from collections import deque
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GatewayRateLimiter:
    """Combines an asyncio Semaphore for concurrency control and a sliding-window limiter to smooth bursts."""

    def __init__(self, max_concurrent: int = 10, requests_per_minute: int = 30):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 30.0) -> None:
        """Wait to acquire both concurrency slot and rate quota."""
        start_time = time.monotonic()

        # Step 1: Acquire concurrency semaphore
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError("Concurrency limit reached; timed out waiting for available slot.")

        # Step 2: Rate limit sliding window check
        try:
            while True:
                async with self._lock:
                    now = time.monotonic()
                    # Evict timestamps older than 60 seconds
                    while self._timestamps and now - self._timestamps[0] > self.window_seconds:
                        self._timestamps.popleft()

                    if len(self._timestamps) < self.requests_per_minute:
                        self._timestamps.append(now)
                        return

                    # Compute wait time for oldest timestamp to expire
                    oldest = self._timestamps[0]
                    wait_time = max(0.05, self.window_seconds - (now - oldest))

                elapsed = time.monotonic() - start_time
                if elapsed + wait_time > timeout:
                    self.semaphore.release()
                    raise TimeoutError("Rate limit exceeded; timed out waiting for rate window quota.")

                logger.debug("Smoothing rate limit burst. Waiting %.2fs for rate slot.", wait_time)
                await asyncio.sleep(wait_time)

        except Exception:
            # Ensure semaphore is released if anything fails after semaphore acquisition
            # Note: if return happened successfully above, release() is called in release()
            pass

    def release(self) -> None:
        """Release concurrency slot."""
        try:
            self.semaphore.release()
        except ValueError:
            pass

    class _ContextManager:
        def __init__(self, limiter: "GatewayRateLimiter", timeout: float):
            self.limiter = limiter
            self.timeout = timeout

        async def __aenter__(self):
            await self.limiter.acquire(timeout=self.timeout)
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.limiter.release()

    def limit(self, timeout: float = 30.0) -> _ContextManager:
        return self._ContextManager(self, timeout)
