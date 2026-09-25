"""Global token-bucket speed limiter."""

from __future__ import annotations

import asyncio
import time

from .config import BLOCK_SIZE


class TokenBucketLimiter:
    """Global token bucket shared by every chunk. rate <= 0 means unlimited."""

    def __init__(self, rate_bytes_per_sec: float = 0):
        self.set_rate(rate_bytes_per_sec)

    def set_rate(self, rate_bytes_per_sec: float) -> None:
        self.rate = max(0.0, float(rate_bytes_per_sec))
        self.capacity = max(self.rate * 0.25, BLOCK_SIZE)   # small burst
        self.tokens = self.capacity
        self._last = time.monotonic()

    async def consume(self, n: int) -> None:
        if self.rate <= 0:
            return
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self._last) * self.rate)
        self._last = now
        self.tokens -= n
        if self.tokens < 0:
            await asyncio.sleep(-self.tokens / self.rate)
