"""3-stage correlation: dedup → group → incident.

process() = persist + correlate (used by tests and inline paths).
correlate() alone is used by the worker on rows the ingest API already
persisted, so ingestion ack never waits on correlation.
"""

import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus
from app.models.base import utcnow
from app.schemas.alerting import NormalizedAlert
from app.services.correlation.dedup import DedupStore
from app.services.correlation.fingerprint import compute_fingerprint, compute_group_key
from app.services.correlation.strategy import CorrelationStrategy

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def build_event(alert: NormalizedAlert, received_at: datetime) -> AlertEvent:
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
    )


class CorrelationEngine:
    def __init__(self, dedup_store: DedupStore, strategies: list[CorrelationStrategy]):
        self.dedup_store = dedup_store
        self.strategies = strategies

    async def process(
        self,
        db: AsyncSession,
        alert: NormalizedAlert,
        config,
        now: datetime | None = None,
    ) -> AlertEvent:
        now = now or utcnow()
        event = build_event(alert, received_at=now)
        db.add(event)
        await db.flush()
        return await self.correlate(db, event, alert, config, now=now)

    async def correlate(
        self,
        db: AsyncSession,
        event: AlertEvent,
        alert: NormalizedAlert,
        config,
        *,
        now: datetime,
    ) -> AlertEvent:
        # Stage 1: dedup — collapse into the previous row, drop this one.
        if await self.dedup_store.seen_within(event.fingerprint, config.dedup_window_seconds):
            prior = await self._latest_other_event(db, event)
            if prior is not None:
                prior.dedup_count += 1
                await db.delete(event)
                await db.flush()
                return prior

        # Stage 2: grouping.
        group_key = compute_group_key(alert.labels, config.group_attrs)
        # Serialize concurrent find-or-create per group_key across replicas.
        # PG-only true-race guard; SQLite (tests) relies on CAS claims +
        # sequential interleaving. Lock is released at tx end.
        if group_key and db.bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:gk))"), {"gk": group_key})
        incident = None
        for strategy in self.strategies:
            incident = await strategy.find_incident(
                db,
                alert,
                group_key,
                now=now,
                window_seconds=config.correlation_window_seconds,
            )
            if incident is not None:
                break

        # Stage 3: incident attach / create.
        if incident is None:
            incident = Incident(
                title=self._title(alert, group_key),
                status=IncidentStatus.open,
                severity=alert.severity,
                group_key=group_key,
                first_seen=now,
                last_seen=now,
                alert_count=0,
            )
            db.add(incident)
            await db.flush()
            db.add(IncidentEvent(incident_id=incident.id, kind="created", payload={}))

        event.incident_id = incident.id
        incident.alert_count += 1
        incident.last_seen = now
        incident.severity = max_severity(incident.severity, alert.severity)
        db.add(
            IncidentEvent(
                incident_id=incident.id,
                kind="alert_attached",
                payload={"alert_event_id": str(event.id), "name": alert.name},
            )
        )
        await db.flush()
        return event

    @staticmethod
    def _title(alert: NormalizedAlert, group_key: str | None) -> str:
        if group_key:
            return f"{alert.name} on {group_key.split('=', 1)[1]}"
        return alert.name

    @staticmethod
    async def _latest_other_event(db: AsyncSession, event: AlertEvent) -> AlertEvent | None:
        res = await db.execute(
            select(AlertEvent)
            .where(AlertEvent.fingerprint == event.fingerprint, AlertEvent.id != event.id)
            .order_by(AlertEvent.received_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()
