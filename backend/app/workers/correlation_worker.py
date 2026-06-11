"""Correlation worker: consumes ingested alert events off the queue and runs
the 3-stage engine. Ingestion ack never waits on this.

Wake-up: Redis stream atlas:alerts:in (best effort). Source of truth:
PG poll for uncorrelated rows (incident_id IS NULL), so events survive
Redis loss and worker downtime.
"""

import asyncio
import logging

import redis.asyncio as aioredis
from sqlalchemy import select

from app.core.config import settings
from app.db import async_session_factory
from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.schemas.alerting import NormalizedAlert
from app.services.correlation.config import get_config
from app.services.correlation.dedup import InMemoryDedupStore, RedisDedupStore
from app.services.correlation.engine import CorrelationEngine
from app.services.correlation.strategy import AttributeTimeStrategy, LLMStrategy

logger = logging.getLogger(__name__)

ALERT_STREAM = "atlas:alerts:in"
CONSUMER_GROUP = "correlation"
POLL_INTERVAL_SECONDS = 5
BATCH_SIZE = 100


def to_normalized(event: AlertEvent) -> NormalizedAlert:
    return NormalizedAlert(
        source=event.source,
        name=event.name,
        severity=event.severity,  # type: ignore[arg-type]
        status=event.status,  # type: ignore[arg-type]
        labels=event.labels or {},
        annotations=event.annotations or {},
        starts_at=event.starts_at,
    )


async def correlate_pending(engine: CorrelationEngine) -> int:
    """Correlates all uncorrelated events, oldest first. Returns count."""
    processed = 0
    async with async_session_factory() as db:
        config = await get_config(db)
        res = await db.execute(
            select(AlertEvent)
            .where(AlertEvent.incident_id.is_(None))
            .order_by(AlertEvent.received_at.asc())
            .limit(BATCH_SIZE)
        )
        for event in list(res.scalars()):
            await engine.correlate(db, event, to_normalized(event), config, now=utcnow())
            processed += 1
        await db.commit()
    return processed


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    redis: aioredis.Redis | None = None
    try:
        redis = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
        try:
            await redis.xgroup_create(ALERT_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        except aioredis.ResponseError:
            pass  # group already exists
    except Exception:
        logger.warning("redis unavailable; falling back to PG polling only")
        redis = None

    dedup = RedisDedupStore(redis) if redis is not None else InMemoryDedupStore()
    engine = CorrelationEngine(
        dedup_store=dedup, strategies=[AttributeTimeStrategy(), LLMStrategy()]
    )

    logger.info("correlation worker started")
    while True:
        try:
            n = await correlate_pending(engine)
            if n:
                logger.info("correlated %d alert events", n)
        except Exception:
            logger.exception("correlation iteration failed")

        # Block on the stream as a wake-up; fall back to a fixed poll interval.
        if redis is not None:
            try:
                entries = await redis.xreadgroup(
                    CONSUMER_GROUP,
                    "worker-1",
                    {ALERT_STREAM: ">"},
                    count=BATCH_SIZE,
                    block=POLL_INTERVAL_SECONDS * 1000,
                )
                for _stream, messages in entries or []:
                    if messages:
                        await redis.xack(ALERT_STREAM, CONSUMER_GROUP, *[m[0] for m in messages])
            except Exception:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        else:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
