"""Token-bucket throttle for outbound sends (Telegram global rate)."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rate = max(rate_per_second, 0.001)
        self._clock = clock
        self._sleeper = sleeper
        self._tokens = self._rate  # burst capacity = 1s worth
        self._last = clock()
        # acquire() is now called concurrently (bounded-gather send pipeline);
        # serialize token math + pacing sleep so depletion stays correct and
        # sustained rate is still capped at _rate.
        self._lock = asyncio.Lock()

    async def acquire(self, address: str) -> None:  # noqa: ARG002 (per-chat later)
        async with self._lock:
            now = self._clock()
            self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await self._sleeper(wait)
                self._last = self._clock()
                self._tokens = 0
            else:
                self._tokens -= 1
