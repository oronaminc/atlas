"""Incident -> notification outbox (IMP §6/§7). Channels come from the
incident's own toggles (notify_email/telegram/oncall); per-user recipients come
from the user-groups mapped to the incident's cmdb_service_l2_code
(group_service_codes). OnCall is a team webhook (one row, no user). Idempotent
via incidents.notified_at CAS + the unique (incident, channel, recipient)
constraint."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import instruments
from app.models import Group, User, UserGroup
from app.models.alerting import Incident, IncidentEvent
from app.models.delivery import Notification
from app.models.group import GroupServiceCode

logger = logging.getLogger(__name__)

SEVERITY_PRIORITY = {"critical": 0, "warning": 1, "info": 2}
FANOUT_BATCH = 50


def severity_priority(severity: str | None) -> int:
    return SEVERITY_PRIORITY.get(severity or "", 1)


def incident_channels(incident: Incident) -> list[str]:
    """Per-incident user-channel toggles (oncall handled separately)."""
    out = []
    if incident.notify_email:
        out.append("email")
    if incident.notify_telegram:
        out.append("telegram")
    return out


async def groups_for_l2(db: AsyncSession, l2_code: str | None) -> list[uuid.UUID]:
    """User-groups mapped to this incident's service-l2 (IMP §6 routing)."""
    if not l2_code:
        return []
    return list(
        (
            await db.execute(
                select(GroupServiceCode.group_id).where(
                    GroupServiceCode.cmdb_service_l2_code == l2_code
                )
            )
        ).scalars()
    )


async def members_of_groups(db: AsyncSession, group_ids: list[uuid.UUID]) -> list[User]:
    if not group_ids:
        return []
    res = await db.execute(
        select(User)
        .join(UserGroup, UserGroup.user_id == User.id)
        .where(UserGroup.group_id.in_(group_ids), User.is_active.is_(True))
    )
    return list(res.scalars().unique())


def build_targets(members: list[User], channels: list[str]) -> list[tuple[str, User, str]]:
    """(channel, user, address) per deliverable per-user target."""
    targets: list[tuple[str, User, str]] = []
    for channel in channels:
        for user in members:
            if channel == "telegram":
                if user.telegram_chat_id:
                    targets.append(("telegram", user, user.telegram_chat_id))
            elif channel == "email":
                targets.append(("email", user, user.email))
    return targets


async def create_notifications(
    db: AsyncSession,
    incident: Incident,
    group_id: uuid.UUID | None,
    targets: list[tuple[str, User, str]],
) -> int:
    """Insert per-user outbox rows, skipping (channel, user) pairs that already
    exist for this incident — safe to call twice."""
    existing = {
        (channel, user_id)
        for channel, user_id in (
            await db.execute(
                select(Notification.channel, Notification.recipient_user_id).where(
                    Notification.incident_id == incident.id
                )
            )
        ).all()
    }
    priority = severity_priority(incident.severity)
    created = 0
    for channel, user, address in targets:
        if (channel, user.id) in existing:
            continue
        db.add(
            Notification(
                incident_id=incident.id,
                tenant_id=incident.tenant_id,
                channel=channel,
                recipient_user_id=user.id,
                recipient_address=address,
                group_id=group_id,
                status="pending",
                priority=priority,
            )
        )
        existing.add((channel, user.id))
        created += 1
    await db.flush()
    return created


async def create_oncall(db: AsyncSession, incident: Incident) -> int:
    """One team-webhook outbox row per incident (recipient_user_id NULL).
    Dedup: skip if an oncall row already exists for the incident."""
    exists = (
        await db.execute(
            select(Notification.id).where(
                Notification.incident_id == incident.id, Notification.channel == "oncall"
            )
        )
    ).first()
    if exists:
        return 0
    db.add(
        Notification(
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            channel="oncall",
            recipient_user_id=None,
            recipient_address=incident.cmdb_service_l2_code or "oncall",
            group_id=None,
            status="pending",
            priority=severity_priority(incident.severity),
        )
    )
    await db.flush()
    return 1


async def fan_out_pending(db: AsyncSession, *, now: datetime) -> int:
    """Claim un-notified incidents (notified_at CAS) and create outbox rows:
    per-user channels (per the incident's toggles) to the members of the groups
    mapped to its l2_code, plus one OnCall row if toggled."""
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

        user_channels = incident_channels(incident)
        group_ids = await groups_for_l2(db, incident.cmdb_service_l2_code)
        if user_channels:
            # per-group so each row keeps its group_id (quota is per-group); a
            # user in several mapped groups is deduped by (channel, user) and
            # attributed to the first group that includes them.
            for gid in group_ids:
                members = await members_of_groups(db, [gid])
                targets = build_targets(members, user_channels)
                created_total += await create_notifications(db, incident, gid, targets)
            # decision I: a user-channel is on but no user-group maps this l2 ->
            # no recipients. Don't drop silently — warn + metric + timeline.
            if not group_ids:
                instruments.incidents_no_recipients.inc()
                logger.warning(
                    "incident %s: channels on but no user-group maps l2=%s",
                    incident.id,
                    incident.cmdb_service_l2_code,
                )
                db.add(
                    IncidentEvent(
                        incident_id=incident.id,
                        tenant_id=incident.tenant_id,
                        kind="no_recipients",
                        payload={"l2_code": incident.cmdb_service_l2_code},
                    )
                )
        if incident.notify_oncall:
            created_total += await create_oncall(db, incident)
    await db.flush()
    return created_total


async def fan_out_to_group(db: AsyncSession, incident: Incident, group: Group) -> int:
    """Manual send to one group on its members' user channels (toggles bypassed)."""
    members = await members_of_groups(db, [group.id])
    targets = build_targets(members, ["telegram", "email"])
    return await create_notifications(db, incident, group.id, targets)
