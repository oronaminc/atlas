"""IMP correlation engine (C1): topology grouping + manual promote/attach/detach.

ONE cohesive engine — the worker (auto path) and the manual API call the same
functions. Auto formation is severity-aware (critical forms immediately at 1;
warning/info need `min_group_size` sharing the topology key within the window)
with retro-attach of free in-window siblings, serialized per topology key by a
PG advisory lock. See app/workers/correlation_worker.py for the per-alert state
machine; this module is the shared mechanism.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus
from app.models.delivery import Notification
from app.models.grouping import GroupingRule
from app.services.correlation.fingerprint import compute_fingerprint
from app.services.grouping_config import get_notification_defaults

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

# topology label key -> the denormalized AlertEvent column it lives in (IMP §5)
_KEY_COLUMN = {
    "cmdb_ci": AlertEvent.cmdb_ci,
    "cmdb_hostname": AlertEvent.cmdb_hostname,
    "cmdb_zone": AlertEvent.cmdb_zone,
    "client_address": AlertEvent.client_address,
    "cmdb_service_l1_code": AlertEvent.cmdb_service_l1_code,
    "cmdb_service_l2_code": AlertEvent.cmdb_service_l2_code,
}


def max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def topology_key(alert: AlertEvent, rule: GroupingRule) -> str | None:
    """Compound topology key value, or None if any component label is absent
    (an alert with no topology key can never auto-group — it stays FREE)."""
    parts = []
    for key in rule.label_keys or []:
        col = _KEY_COLUMN.get(key)
        value = getattr(alert, col.key, None) if col is not None else None
        if not value:
            return None
        parts.append(f"{key}={value}")
    return ";".join(parts) if parts else None


def _primary_column(rule: GroupingRule):
    """The denorm column for the rule's first label key (v1: single key)."""
    return _KEY_COLUMN[rule.label_keys[0]]


def _window_match(rule: GroupingRule, alert: AlertEvent, now: datetime):
    col = _primary_column(rule)
    value = getattr(alert, col.key)
    window_start = now - timedelta(seconds=rule.window_seconds)
    return col == value, window_start


async def _advisory_lock(db: AsyncSession, key: str) -> None:
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})


async def find_open_incident(
    db: AsyncSession, key: str, rule: GroupingRule, now: datetime
) -> Incident | None:
    cutoff = now - timedelta(seconds=rule.window_seconds)
    return (
        await db.execute(
            select(Incident)
            .where(
                Incident.group_key == key,
                Incident.status != IncidentStatus.resolved,
                Incident.last_seen >= cutoff,
            )
            .order_by(Incident.last_seen.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _count_free(
    db: AsyncSession, rule: GroupingRule, alert: AlertEvent, now: datetime
) -> int:
    match, window_start = _window_match(rule, alert, now)
    return (
        await db.execute(
            select(func.count())
            .select_from(AlertEvent)
            .where(
                match,
                AlertEvent.incident_id.is_(None),
                AlertEvent.suppressed.isnot(True),
                AlertEvent.received_at >= window_start,
            )
        )
    ).scalar_one()


def _denorm_from_alert(inc: Incident, alert: AlertEvent) -> None:
    inc.cmdb_service_l2_code = alert.cmdb_service_l2_code
    inc.cmdb_service_l1_code = alert.cmdb_service_l1_code
    inc.cmdb_zone = alert.cmdb_zone


def _title(alert: AlertEvent, key: str | None) -> str:
    # human scope = the cmdb_service_l2 display label, falling back to the key value
    scope = (alert.labels or {}).get("cmdb_service_l2") or (key.split("=", 1)[-1] if key else "")
    return f"{alert.name} — {scope}" if scope else alert.name


async def _new_incident(
    db: AsyncSession,
    alert: AlertEvent,
    *,
    key: str | None,
    origin: str,
    rule: GroupingRule | None,
    now: datetime,
    title: str | None = None,
) -> Incident:
    defaults = await get_notification_defaults(db)
    inc = Incident(
        title=title or _title(alert, key),
        status=IncidentStatus.open,
        severity=alert.severity,
        group_key=key,
        first_seen=now,
        last_seen=now,
        alert_count=0,
        origin=origin,
        grouping_rule_id=rule.id if rule is not None else None,
        notify_email=defaults.default_email,
        notify_telegram=defaults.default_telegram,
        notify_oncall=defaults.default_oncall,
    )
    _denorm_from_alert(inc, alert)
    db.add(inc)
    await db.flush()
    db.add(IncidentEvent(incident_id=inc.id, kind="created", payload={"origin": origin}))
    return inc


async def _timeline(db: AsyncSession, inc: Incident, kind: str, payload: dict) -> None:
    db.add(IncidentEvent(incident_id=inc.id, kind=kind, payload=payload))


async def attach_alert(
    db: AsyncSession, inc: Incident, alert: AlertEvent, now: datetime, *, manual: bool = False
) -> None:
    if alert.incident_id is not None and alert.incident_id != inc.id:
        raise AlreadyAttachedError(alert.id, alert.incident_id)
    alert.incident_id = inc.id
    alert.correlated = True
    inc.alert_count += 1
    inc.last_seen = now  # now monotonically advances; avoids naive/aware compare
    inc.severity = max_severity(inc.severity, alert.severity)
    await _timeline(
        db,
        inc,
        "alert_attached_manual" if manual else "alert_attached",
        {"alert_event_id": str(alert.id), "name": alert.name},
    )


async def _retro_attach(
    db: AsyncSession, inc: Incident, rule: GroupingRule, alert: AlertEvent, now: datetime
) -> int:
    """Pull every FREE in-window same-key alert (this alert + earlier siblings)
    into the incident with ONE bulk UPDATE — the retro-attach. Direct UPDATE, not
    a claim, so already-processed free alerts join without being re-claimed."""
    match, window_start = _window_match(rule, alert, now)
    res = await db.execute(
        update(AlertEvent)
        .where(
            match,
            AlertEvent.incident_id.is_(None),
            AlertEvent.suppressed.isnot(True),
            AlertEvent.received_at >= window_start,
        )
        .values(incident_id=inc.id, correlated=True)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount


class AlreadyAttachedError(Exception):
    """Manual attach of an alert already in a different incident (decision H)."""

    def __init__(self, alert_id: uuid.UUID, incident_id: uuid.UUID):
        self.alert_id = alert_id
        self.incident_id = incident_id
        super().__init__(f"alert {alert_id} already attached to incident {incident_id}")


async def group_alert(
    db: AsyncSession, alert: AlertEvent, rule: GroupingRule, now: datetime
) -> Incident | None:
    """Auto path (worker). Returns the incident the alert ended up in, or None if
    it stays FREE. Caller sets alert.correlated=True afterwards."""
    # 0. already attached (retro-attached by an earlier sibling in this batch)
    if alert.incident_id is not None:
        return await db.get(Incident, alert.incident_id)
    # 3. no topology key -> stays free
    key = topology_key(alert, rule)
    if key is None:
        return None
    # 4. serialize formation per key across replicas
    await _advisory_lock(db, key)
    # under the lock, re-read incident_id: another worker may have retro-attached
    # this alert (committed) while we were blocked. Without this re-read its stale
    # in-memory NULL would let us double-attach it.
    await db.refresh(alert, ["incident_id"])
    if alert.incident_id is not None:
        return await db.get(Incident, alert.incident_id)
    # 5. existing open incident in-window -> attach
    open_inc = await find_open_incident(db, key, rule, now)
    if open_inc is not None:
        await attach_alert(db, open_inc, alert, now)
        return open_inc
    # 6-7. severity-aware formation
    count = await _count_free(db, rule, alert, now)
    if count >= rule.threshold_for(alert.severity):
        inc = await _new_incident(db, alert, key=key, origin="auto", rule=rule, now=now)
        n = await _retro_attach(db, inc, rule, alert, now)
        # the bulk UPDATE (synchronize_session=False) doesn't refresh the trigger
        # alert's in-memory state; set it explicitly so the caller sees it attached
        alert.incident_id = inc.id
        alert.correlated = True
        inc.alert_count = n
        await db.flush()
        await _timeline(db, inc, "alert_attached", {"retro_attached": n})
        return inc
    return None  # lone non-critical -> stays free


# --- manual entry points (shared with the worker via the helpers above) ---


async def promote_alert(
    db: AsyncSession, alert: AlertEvent, now: datetime, *, title: str | None = None
) -> Incident:
    """Manual: promote a single alert into a NEW incident (any severity, size 1,
    threshold bypassed)."""
    if alert.incident_id is not None:
        raise AlreadyAttachedError(alert.id, alert.incident_id)
    # manual incidents carry no group_key, so auto-grouping never attaches to them
    inc = await _new_incident(db, alert, key=None, origin="manual", rule=None, now=now, title=title)
    await attach_alert(db, inc, alert, now, manual=True)
    await _timeline(db, inc, "promoted", {"alert_event_id": str(alert.id)})
    return inc


async def attach_to_incident(
    db: AsyncSession, inc: Incident, alert: AlertEvent, now: datetime
) -> None:
    """Manual attach of an alert into an existing incident."""
    await attach_alert(db, inc, alert, now, manual=True)


class LastAlertError(Exception):
    """Detach of an incident's last alert (A4): an incident can never have 0
    alerts — dissolve it with DELETE /incidents/{id} instead."""

    def __init__(self, incident_id: uuid.UUID):
        self.incident_id = incident_id
        super().__init__(f"incident {incident_id} would be emptied; delete it to dissolve")


async def resolve_if_all_resolved(db: AsyncSession, inc: Incident, now: datetime) -> bool:
    """If every member alert is resolved, move the incident to resolved (system
    actor) — the universal terminal regardless of prior state (open/ack/suppressed).
    Idempotent; no-op on an already-resolved incident."""
    if inc.status == IncidentStatus.resolved:
        return False
    await db.flush()  # ensure just-set alert statuses are visible to the counts
    total = (
        await db.execute(
            select(func.count()).select_from(AlertEvent).where(AlertEvent.incident_id == inc.id)
        )
    ).scalar_one()
    if total == 0:
        return False
    unresolved = (
        await db.execute(
            select(func.count())
            .select_from(AlertEvent)
            .where(AlertEvent.incident_id == inc.id, AlertEvent.status != "resolved")
        )
    ).scalar_one()
    if unresolved == 0:
        inc.status = IncidentStatus.resolved
        await _timeline(
            db,
            inc,
            "status_changed",
            {"to": "resolved", "reason": "all alerts resolved", "actor": "system"},
        )
        return True
    return False


async def detach_alert(db: AsyncSession, inc: Incident, alert: AlertEvent, now: datetime) -> None:
    """Manual detach (A4). Blocks emptying the incident (1->0 forbidden) — a
    detached alert stays FREE (incident_id NULL, correlated=True), browsable and
    manually re-attachable, never auto-re-grouped. After detach, if the remaining
    alerts are all resolved the incident auto-resolves."""
    if alert.incident_id != inc.id:
        return
    if inc.alert_count <= 1:
        raise LastAlertError(inc.id)
    alert.incident_id = None
    inc.alert_count -= 1
    await _timeline(db, inc, "alert_detached", {"alert_event_id": str(alert.id)})
    await resolve_if_all_resolved(db, inc, now)


async def delete_incident(db: AsyncSession, inc: Incident) -> int:
    """Dissolve an incident (A4): free ALL its alerts (incident_id NULL, keep
    correlated so they don't auto-regroup), drop its timeline + its pending/failed
    notifications, then delete the incident. Already-sent/dead notifications are
    kept as the delivery record (FK SET NULL orphans them). Returns freed count."""
    await db.execute(
        delete(Notification).where(
            Notification.incident_id == inc.id,
            Notification.status.in_(("pending", "failed")),
        )
    )
    # keep sent/dead as the delivery record — orphan them explicitly (don't rely
    # on FK SET NULL: SQLite doesn't enforce FK actions by default).
    await db.execute(
        update(Notification)
        .where(Notification.incident_id == inc.id)
        .values(incident_id=None)
        .execution_options(synchronize_session=False)
    )
    freed = (
        await db.execute(
            update(AlertEvent)
            .where(AlertEvent.incident_id == inc.id)
            .values(incident_id=None)
            .execution_options(synchronize_session=False)
        )
    ).rowcount
    await db.delete(inc)  # cascade-deletes the timeline (ORM relationship cascade)
    return freed


async def resolve_incoming(
    db: AsyncSession, source: str, name: str, labels: dict, now: datetime
) -> bool:
    """An Alertmanager 'resolved' element (incl. per-element in a batched webhook):
    match the stored alert by fingerprint (= ingest dedup identity), flip it to
    resolved by the SYSTEM, and auto-resolve its incident if all alerts are now
    resolved. No matching stored alert -> no-op."""
    fp = compute_fingerprint(source, name, labels)
    alert = (
        await db.execute(
            select(AlertEvent)
            .where(AlertEvent.fingerprint == fp, AlertEvent.status != "resolved")
            .order_by(AlertEvent.received_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if alert is None:
        return False
    alert.status = "resolved"
    if alert.incident_id is not None:
        inc = await db.get(Incident, alert.incident_id)
        if inc is not None:
            await _timeline(
                db,
                inc,
                "alert_resolved",
                {"alert_event_id": str(alert.id), "source": "alertmanager", "actor": "system"},
            )
            await resolve_if_all_resolved(db, inc, now)
    return True
