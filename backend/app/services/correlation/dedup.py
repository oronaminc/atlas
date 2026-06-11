"""Stage-1 dedup window. Sliding: every occurrence refreshes the window."""

import time
from collections.abc import Callable
from typing import Protocol

import redis.asyncio as aioredis


class DedupStore(Protocol):
    async def seen_within(self, fingerprint: str, window_seconds: int) -> bool: ...


class InMemoryDedupStore:
    """Test/fallback store with an injectable clock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_seen: dict[str, float] = {}

    async def seen_within(self, fingerprint: str, window_seconds: int) -> bool:
        now = self._clock()
        last = self._last_seen.get(fingerprint)
        self._last_seen[fingerprint] = now
        return last is not None and (now - last) < window_seconds


class RedisDedupStore:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def seen_within(self, fingerprint: str, window_seconds: int) -> bool:
        key = f"atlas:dedup:{fingerprint}"
        # GETSET-style: read previous marker, then refresh the window.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.exists(key)
            pipe.set(key, "1", ex=window_seconds)
            existed, _ = await pipe.execute()
        return bool(existed)
