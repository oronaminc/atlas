"""/metrics — Prometheus exposition for the API process.

Exposes this process's own counters (ingest) PLUS the cross-pod DB-derived
gauges (queue depth, oldest-pending age, backlog, default-partition rows,
rollup lag, per-service soft-cap breaches). DB gauges are recomputed at most
every METRICS_DB_CACHE_SECONDS so frequent scrapes don't hammer PG.

INFRA-INTERNAL: unauthenticated, NOT behind the tenancy choke point (opens its
own unscoped session to see all services — correct for ops). Must not be routed
through the public Ingress; scrape via ClusterIP/pod IP only (see NetworkPolicy
+ pod annotations in deploy/k8s).
"""

import time

from fastapi import APIRouter, Response
from sqlalchemy import func, select, text

import app.core.instruments as m
from app.core.config import settings
from app.core.metrics import CONTENT_TYPE, REGISTRY
from app.db import async_session_factory
from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.models.delivery import Notification, NotificationSettings
from app.models.tenant import Tenant
from app.services.maintenance import default_partition_count

router = APIRouter(tags=["metrics"])

_cache: dict = {"at": 0.0}


async def refresh_db_gauges() -> None:
    """Open an UNSCOPED session and recompute the cross-pod gauges."""
    async with async_session_factory() as db:
        await collect_db_gauges(db)


async def collect_db_gauges(db) -> None:
    """Recompute the DB-derived gauges on the given (unscoped) session."""
    now = utcnow()
    if True:

        # correlation backlog (uncorrelated within claim lookback)
        backlog = (
            await db.execute(
                select(func.count()).select_from(AlertEvent).where(AlertEvent.incident_id.is_(None))
            )
        ).scalar_one()
        m.correlation_backlog.set(backlog)
        oldest = (
            await db.execute(
                select(func.min(AlertEvent.received_at)).where(AlertEvent.incident_id.is_(None))
            )
        ).scalar_one()
        m.correlation_oldest_seconds.set(_age(now, oldest))

        # notification queue
        pending = (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.status.in_(("pending", "failed")))
            )
        ).scalar_one()
        m.notifications_pending.set(pending)
        oldest_n = (
            await db.execute(
                select(func.min(Notification.created_at)).where(
                    Notification.status.in_(("pending", "failed"))
                )
            )
        ).scalar_one()
        m.notifications_oldest_pending_seconds.set(_age(now, oldest_n))
        dead = (
            await db.execute(
                select(func.count()).select_from(Notification).where(Notification.status == "dead")
            )
        ).scalar_one()
        m.notifications_dead_gauge.set(dead)

        # rollup freshness
        last_bucket = (
            await db.execute(text("SELECT max(bucket_start) FROM alert_stats_hourly"))
        ).scalar_one_or_none()
        m.rollup_lag_seconds.set(_age(now, last_bucket))

        # default-partition rows (PG only; should be 0)
        m.default_partition_rows.set(await default_partition_count(db))

        # per-service soft-cap breaches — BREACH-ONLY series (cardinality bound)
        await _refresh_softcap(db)


async def _refresh_softcap(db) -> None:
    # per-service pending counts joined to slug + that service's cap
    rows = (
        await db.execute(
            select(Tenant.slug, Notification.tenant_id, func.count())
            .select_from(Notification)
            .join(Tenant, Tenant.id == Notification.tenant_id, isouter=True)
            .where(Notification.status.in_(("pending", "failed")))
            .group_by(Tenant.slug, Notification.tenant_id)
        )
    ).all()
    caps = {
        tid: cap
        for tid, cap in (
            await db.execute(
                select(NotificationSettings.tenant_id, NotificationSettings.pending_softcap)
            )
        ).all()
    }
    default_cap = settings.NOTIFY_PENDING_SOFTCAP
    m.tenant_pending_softcap_breached.clear()  # only re-emit current breaches
    for slug, tenant_id, count in rows:
        cap = caps.get(tenant_id, default_cap) or default_cap
        if count > cap:
            m.tenant_pending_softcap_breached.set(1, service=slug or "(none)")


def _age(now, ts) -> float:
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        from datetime import UTC

        ts = ts.replace(tzinfo=UTC)
    return max(0.0, (now - ts).total_seconds())


@router.get("/metrics")
async def metrics() -> Response:
    if time.monotonic() - _cache["at"] >= settings.METRICS_DB_CACHE_SECONDS:
        try:
            await refresh_db_gauges()
            _cache["at"] = time.monotonic()
        except Exception:  # never let a metrics scrape 500 the endpoint
            pass
    return Response(content=REGISTRY.render(), media_type=CONTENT_TYPE)
