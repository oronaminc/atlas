"""Correlation worker: claims ingested alert events (CAS + lease, safe at
replicas>1) and runs the 3-stage engine. PG is the source of truth; the
Redis stream is only a wake-up. Crashed workers' claims expire after the
lease and another pod resumes the work.
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import instruments
from app.core.config import settings
from app.db import async_session_factory
from app.integrations.mimir_ruler import MimirQueryClient
from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.schemas.alerting import NormalizedAlert
from app.services.correlation.config import get_config
from app.services.correlation.dedup import InMemoryDedupStore, RedisDedupStore
from app.services.correlation.engine import CorrelationEngine
from app.services.correlation.strategy import AttributeTimeStrategy, LLMStrategy
from app.services.rule_sync import org_for_tenant
from app.services.threshold import ValueCache, parse_instant_value, should_suppress
from app.workers.metrics_server import heartbeat, start_metrics_server

logger = logging.getLogger(__name__)

ALERT_STREAM = "atlas:alerts:in"
CONSUMER_GROUP = "correlation"
POLL_INTERVAL_SECONDS = 5
BATCH_SIZE = 100
DEFAULT_LEASE_SECONDS = 60

WORKER_ID = os.environ.get("HOSTNAME") or f"correlation-{uuid.uuid4().hex[:8]}"


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


async def claim_events(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    limit: int = BATCH_SIZE,
) -> list[AlertEvent]:
    """CAS+lease claim of uncorrelated events; exclusive across replicas."""
    lease_cutoff = now - timedelta(seconds=lease_seconds)
    guard = (
        AlertEvent.incident_id.is_(None),
        AlertEvent.suppressed.isnot(True),  # threshold-dropped events are terminal
        or_(AlertEvent.claimed_at.is_(None), AlertEvent.claimed_at < lease_cutoff),
        # partition pruning: never scan further back than the claim lookback
        # (events older than this are operationally dead anyway)
        AlertEvent.received_at >= now - timedelta(days=settings.CLAIM_LOOKBACK_DAYS),
    )

    candidates = (
        select(AlertEvent.id).where(*guard).order_by(AlertEvent.received_at.asc()).limit(limit)
    )
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)
    candidate_ids = list((await db.execute(candidates)).scalars())
    if not candidate_ids:
        return []

    claimed_ids = []
    for event_id in candidate_ids:
        result = await db.execute(
            update(AlertEvent)
            .where(AlertEvent.id == event_id, *guard)
            .values(claimed_at=now, claimed_by=worker_id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            claimed_ids.append(event_id)
    if not claimed_ids:
        return []

    res = await db.execute(
        select(AlertEvent)
        .where(AlertEvent.id.in_(claimed_ids))
        .order_by(AlertEvent.received_at.asc())
        .execution_options(populate_existing=True)
    )
    return list(res.scalars())


def _make_fetch_value(db: AsyncSession):
    """Per-tenant Mimir value fetch for the threshold filter. Resolves the
    tenant's Mimir org (X-Scope-OrgID) and runs an instant query; the caller
    (should_suppress) treats exceptions/None as fail-open."""

    async def fetch_value(tenant_id, promql: str) -> float | None:
        org = await org_for_tenant(db, tenant_id)
        client = MimirQueryClient(org=org)
        resp = await client.instant_query(promql)
        return parse_instant_value(resp)

    return fetch_value


async def correlate_pending(engine: CorrelationEngine, cache: ValueCache) -> int:
    processed = 0
    t0 = time.perf_counter()
    async with async_session_factory() as db:
        config = await get_config(db)
        fetch_value = _make_fetch_value(db)
        for event in await claim_events(db, worker_id=WORKER_ID, now=utcnow()):
            suppress, value = await should_suppress(db, event, fetch_value=fetch_value, cache=cache)
            if value is not None:
                event.value = value  # audit: record the fetched value
            if suppress:
                event.suppressed = True  # stored, NOT escalated; excluded from re-claim
                processed += 1
                continue
            await engine.correlate(db, event, to_normalized(event), config, now=utcnow())
            processed += 1
        await db.commit()
    instruments.correlation_batch_seconds.observe(time.perf_counter() - t0)
    instruments.correlation_iterations.inc(outcome="busy" if processed else "idle")
    return processed


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    await start_metrics_server("correlation", port=settings.METRICS_PORT)

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
    instruments.redis_up.set(1 if redis is not None else 0)

    dedup = RedisDedupStore(redis) if redis is not None else InMemoryDedupStore()
    engine = CorrelationEngine(
        dedup_store=dedup, strategies=[AttributeTimeStrategy(), LLMStrategy()]
    )
    value_cache = ValueCache()  # short-TTL cache for threshold-filter Mimir reads

    logger.info("correlation worker %s started", WORKER_ID)
    while True:
        try:
            n = await correlate_pending(engine, value_cache)
            if n:
                logger.info("correlated %d alert events", n)
        except Exception:
            logger.exception("correlation iteration failed")
        heartbeat("correlation")

        # Block on the stream as a wake-up; fall back to a fixed poll interval.
        if redis is not None:
            try:
                entries = await redis.xreadgroup(
                    CONSUMER_GROUP,
                    WORKER_ID,
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
