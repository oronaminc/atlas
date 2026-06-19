"""Notification mute evaluation (PR #1).

A NotificationMute suppresses notifications for a (target x alertname) combo,
with wildcards: NULL alertname = all rules; target_type 'all' = every target;
'server' matches by cmdb_ci; 'group' matches the server's (single) group.

Incident-level rule: an incident is muted iff it carries >=1 (cmdb_ci, alertname)
pair AND EVERY such pair is muted — so an incident that still contains a
non-muted alert is never silenced.

Runs in the notification worker (unscoped), so every query filters by the
incident's tenant_id explicitly — same pattern as route matching.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import AlertEvent, Incident
from app.models.delivery import NotificationMute
from app.models.server import Server


def _pair_muted(
    cmdb_ci: str | None,
    alertname: str,
    group_id: uuid.UUID | None,
    mutes: list[NotificationMute],
) -> bool:
    for m in mutes:
        if m.alertname is not None and m.alertname != alertname:
            continue  # this mute targets a different rule
        if m.target_type == "all":
            return True
        if m.target_type == "server" and cmdb_ci is not None and m.target_cmdb_ci == cmdb_ci:
            return True
        if m.target_type == "group" and group_id is not None and m.target_group_id == group_id:
            return True
    return False


async def is_incident_muted(db: AsyncSession, incident: Incident) -> bool:
    pairs = {
        (((labels or {}).get("cmdb_ci")), name)
        for name, labels in (
            await db.execute(
                select(AlertEvent.name, AlertEvent.labels).where(
                    AlertEvent.incident_id == incident.id
                )
            )
        ).all()
    }
    if not pairs:
        return False

    mutes = list(
        (
            await db.execute(
                select(NotificationMute).where(
                    NotificationMute.tenant_id == incident.tenant_id,
                    NotificationMute.enabled.is_(True),
                )
            )
        ).scalars()
    )
    if not mutes:
        return False

    cmdbs = {c for c, _ in pairs if c}
    group_of: dict[str, uuid.UUID | None] = {}
    if cmdbs:
        group_of = {
            c: g
            for c, g in (
                await db.execute(
                    select(Server.cmdb_ci, Server.server_group_id).where(
                        Server.tenant_id == incident.tenant_id,
                        Server.cmdb_ci.in_(cmdbs),
                    )
                )
            ).all()
        }

    return all(_pair_muted(c, name, group_of.get(c), mutes) for c, name in pairs)
