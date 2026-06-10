import time

import redis.asyncio as aioredis

from app.core.config import settings


class RateLimiter:
    """Fixed-window rate limiter backed by Redis, with an in-memory fallback
    so tests and degraded environments keep working."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._memory: dict[str, tuple[int, float]] = {}

    def _client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Returns True if the call is allowed, False if rate-limited."""
        full_key = f"ratelimit:{key}"
        try:
            client = self._client()
            count = await client.incr(full_key)
            if count == 1:
                await client.expire(full_key, window_seconds)
            return count <= limit
        except Exception:
            now = time.monotonic()
            count, started = self._memory.get(full_key, (0, now))
            if now - started > window_seconds:
                count, started = 0, now
            count += 1
            self._memory[full_key] = (count, started)
            return count <= limit


login_rate_limiter = RateLimiter()
