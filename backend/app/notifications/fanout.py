"""Incident -> notification outbox (IMP §6/§7, per-group channels).

Routing: incident -> the user-groups mapped to its cmdb_service_l2_code
(group_service_codes) -> each group's OWN configured channels (group_channels:
its telegram bot+chats, emails, oncall webhook). The incident's per-channel
toggles (notify_email/telegram/oncall) gate which channel types fire. Nothing
is global. Idempotent via incidents.notified_at CAS + the unique
(incident, channel, recipient_address) constraint.
"""

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import instruments
from app.models import Group
from app.models.alerting import Incident, IncidentEvent
from app.models.delivery import GroupChannel, Notification
from app.models.group import GroupServiceCode

logger = logging.getLogger(__name__)

SEVERITY_PRIORITY = {"critical": 0, "warning": 1, "info": 2}
FANOUT_BATCH = 50


def severity_priority(severity: str | None) -> int:
    return SEVERITY_PRIORITY.get(severity or "", 1)


def enabled_channels(incident: Incident) -> set[str]:
    """The channel types the incident's toggles enable."""
    out: set[str] = set()
    if incident.notify_email:
        out.add("email")
    if incident.notify_telegram:
        out.add("telegram")
    if incident.notify_oncall:
        out.add("oncall")
    return out


def channel_address(gc: GroupChannel) -> str:
    """The destination recorded on the outbox row (dedup key + display).
    The secret (bot token / webhook) is resolved from group_channel_id at send."""
    if gc.channel == "telegram":
        return gc.chat_id or ""
    if gc.channel == "email":
        return gc.email or ""
    if gc.channel == "oncall":
        return f"oncall:{gc.group_id}"  # one oncall per group; unique per group
    return ""


async def group_channels_for_l2(db: AsyncSession, l2_code: str | None) -> list[GroupChannel]:
    """Enabled channels of every user-group mapped to this incident's l2."""
    if not l2_code:
        return []
    return list(
        (
            await db.execute(
                select(GroupChannel)
                .join(GroupServiceCode, GroupServiceCode.group_id == GroupChannel.group_id)
                .where(
                    GroupServiceCode.cmdb_service_l2_code == l2_code,
                    GroupChannel.enabled.is_(True),
                )
            )
        )
        .scalars()
        .unique()
    )


async def _create_for_channels(
    db: AsyncSession, incident: Incident, channels: list[GroupChannel]
) -> int:
    """Insert one outbox row per (channel, destination), skipping dups — safe to
    call twice (idempotent on the unique (incident, channel, recipient_address))."""
    existing = {
        (channel, addr)
        for channel, addr in (
            await db.execute(
                select(Notification.channel, Notification.recipient_address).where(
                    Notification.incident_id == incident.id
                )
            )
        ).all()
    }
    priority = severity_priority(incident.severity)
    created = 0
    for gc in channels:
        addr = channel_address(gc)
        if not addr or (gc.channel, addr) in existing:
            continue
        db.add(
            Notification(
                incident_id=incident.id,
                channel=gc.channel,
                recipient_user_id=None,
                recipient_address=addr,
                group_id=gc.group_id,
                group_channel_id=gc.id,
                status="pending",
                priority=priority,
            )
        )
        existing.add((gc.channel, addr))
        created += 1
    await db.flush()
    return created


async def fan_out_pending(db: AsyncSession, *, now: datetime) -> int:
    """Claim un-notified incidents (notified_at CAS) and create outbox rows for
    each group-channel (of the groups mapped to the incident's l2) whose channel
    type the incident's toggles enable."""
    stmt = select(Incident.id).where(Incident.notified_at.is_(None)).limit(FANOUT_BATCH)
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    candidate_ids = list((await db.execute(stmt)).scalars())

    created_total = 0
    for incident_id in candidate_ids:
        claimed = await db.execute(
            update(Incident)
            .where(Incident.id == incident_id, Incident.notified_at.is_(None))
            .values(notified_at=now)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 0:
            continue  # another pod won
        incident = await db.get(Incident, incident_id)
        await db.refresh(incident)

        toggles = enabled_channels(incident)
        if not toggles:
            continue
        all_channels = await group_channels_for_l2(db, incident.cmdb_service_l2_code)
        matched = [gc for gc in all_channels if gc.channel in toggles]
        created_total += await _create_for_channels(db, incident, matched)
        # decision I: channels toggled on but no mapped group / no matching channel
        # configured -> no recipients. Warn + metric + timeline, never crash.
        if not matched:
            instruments.incidents_no_recipients.inc()
            logger.warning(
                "incident %s: channels %s on but no group-channel maps l2=%s",
                incident.id,
                sorted(toggles),
                incident.cmdb_service_l2_code,
            )
            db.add(
                IncidentEvent(
                    incident_id=incident.id,
                    kind="no_recipients",
                    payload={"l2_code": incident.cmdb_service_l2_code, "channels": sorted(toggles)},
                )
            )
    await db.flush()
    return created_total


async def fan_out_to_group(db: AsyncSession, incident: Incident, group: Group) -> int:
    """Manual send to one group on ALL its enabled channels (toggles bypassed)."""
    channels = list(
        (
            await db.execute(
                select(GroupChannel).where(
                    GroupChannel.group_id == group.id, GroupChannel.enabled.is_(True)
                )
            )
        )
        .scalars()
        .unique()
    )
    return await _create_for_channels(db, incident, channels)
