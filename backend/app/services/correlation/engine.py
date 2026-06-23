"""Correlation helpers shared by ingest + the IMP correlation worker.

The legacy 3-stage CorrelationEngine/strategy was removed in the IMP redesign;
formation now lives in `app/services/incident_service.py` (topology grouping)
driven by `app/workers/correlation_worker.py`. What survives here is the pure,
stateless plumbing both paths still need: build a denormalized AlertEvent from a
NormalizedAlert, and find the dedup-collapse target within a window.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent
from app.schemas.alerting import NormalizedAlert
from app.services.correlation.fingerprint import compute_fingerprint

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


# Canonical inbound label keys (IMP §4) denormalized onto alert columns at
# ingest, so the label-based query model + l2-visibility get indexed columns.
# Each maps 1:1 to an AlertEvent column; a missing label -> NULL.
_DENORM_KEYS = (
    "cmdb_ci",
    "cmdb_hostname",
    "cmdb_zone",
    "client_address",
    "cmdb_service_l1_code",
    "cmdb_service_l2_code",
)


def build_event(alert: NormalizedAlert, received_at: datetime) -> AlertEvent:
    from app.services.threshold import value_from_annotations

    labels = alert.labels or {}
    return AlertEvent(
        fingerprint=compute_fingerprint(alert.source, alert.name, alert.labels),
        source=alert.source,
        name=alert.name,
        severity=alert.severity,
        status=alert.status,
        labels=alert.labels,
        annotations=alert.annotations,
        starts_at=alert.starts_at,
        received_at=received_at,
        # the alert's carried metric value (threshold filter compares this; no query)
        value=value_from_annotations(alert.annotations),
        **{key: labels.get(key) for key in _DENORM_KEYS},
    )


async def latest_other_event(
    db: AsyncSession, event: AlertEvent, *, window_seconds: int, now: datetime
) -> AlertEvent | None:
    """Most recent other alert with the same fingerprint within the dedup window
    (the dedup collapse target). The received_at lower bound lets PG prune the
    partitioned alert_events down to 1-2 daily partitions."""
    res = await db.execute(
        select(AlertEvent)
        .where(
            AlertEvent.fingerprint == event.fingerprint,
            AlertEvent.id != event.id,
            AlertEvent.received_at >= now - timedelta(seconds=window_seconds),
        )
        .order_by(AlertEvent.received_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()
