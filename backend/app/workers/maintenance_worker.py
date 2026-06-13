"""Maintenance worker (separate pod): partitions ahead, DEFAULT re-homing,
retention drops/deletes (+ optional archive), hourly rollups.

Runs a full pass on start, then every MAINTENANCE_INTERVAL_SECONDS (6h).
Rollups alone refresh every ROLLUP_INTERVAL_SECONDS (15min) so /stats stays
fresh; the stats endpoints additionally live-scan everything after the last
rolled-up hour, so worker downtime degrades latency, never correctness.
A Redis lock (sync-worker pattern) prevents concurrent passes across pods.
"""

import asyncio
import logging

import redis.asyncio as aioredis

from app.core.config import settings
from app.db import async_session_factory
from app.services.maintenance import rollup_hourly, run_maintenance

logger = logging.getLogger(__name__)

LOCK_KEY = "atlas:maintenance:lock"
LOCK_TTL_SECONDS = 600
MAINTENANCE_INTERVAL_SECONDS = 6 * 3600
ROLLUP_INTERVAL_SECONDS = 15 * 60


async def run_once(redis: aioredis.Redis | None, *, full: bool) -> None:
    if redis is not None:
        acquired = await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            logger.debug("another worker holds the maintenance lock; skipping")
            return
    try:
        async with async_session_factory() as db:
            if full:
                summary = await run_maintenance(db)
                await db.commit()
                logger.info("maintenance pass: %s", summary)
                if summary["default_partition_rows"]:
                    logger.warning(
                        "DEFAULT partition holds %d rows after re-homing",
                        summary["default_partition_rows"],
                    )
            else:
                n = await rollup_hourly(db)
                await db.commit()
                logger.info("rollup refresh: %d buckets", n)
    finally:
        if redis is not None:
            try:
                await redis.delete(LOCK_KEY)
            except Exception:
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        redis: aioredis.Redis | None = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
    except Exception:
        logger.warning("redis unavailable; running without the maintenance lock")
        redis = None

    logger.info("maintenance worker started (full=%ss)", MAINTENANCE_INTERVAL_SECONDS)
    elapsed_since_full = MAINTENANCE_INTERVAL_SECONDS  # full pass on start
    while True:
        full = elapsed_since_full >= MAINTENANCE_INTERVAL_SECONDS
        try:
            await run_once(redis, full=full)
        except Exception:
            logger.exception("maintenance iteration failed")
        if full:
            elapsed_since_full = 0
        await asyncio.sleep(ROLLUP_INTERVAL_SECONDS)
        elapsed_since_full += ROLLUP_INTERVAL_SECONDS


if __name__ == "__main__":
    asyncio.run(main())
