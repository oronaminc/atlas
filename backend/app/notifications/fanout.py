"""Incident → route match → outbox rows. Idempotent via incidents.notified_at
CAS + the unique (incident, channel, recipient) constraint."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, User, UserGroup
from app.models.alerting import Incident
from app.models.delivery import Notification, NotificationRoute

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
FANOUT_BATCH = 50


async def group_member_users(db: AsyncSession, group_id: uuid.UUID) -> list[User]:
    res = await db.execute(
        select(User)
        .join(UserGroup, UserGroup.user_id == User.id)
        .where(UserGroup.group_id == group_id, User.is_active.is_(True))
    )
    return list(res.scalars().unique())


def build_targets(members: list[User], channels: list[str]) -> list[tuple[str, User, str]]:
    """(channel, user, address) per deliverable target."""
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
    """Inserts outbox rows, skipping (incident, channel, user) pairs that
    already exist — safe to call twice."""
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
            )
        )
        existing.add((channel, user.id))
        created += 1
    await db.flush()
    return created


async def fan_out_pending(db: AsyncSession, *, now: datetime) -> int:
    """Scans un-notified incidents, claims each via notified_at CAS, and
    creates outbox rows for every enabled matching route. Returns rows created."""
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
        severity_rank = SEVERITY_RANK.get(incident.severity, 0)
        # routes are tenant-scoped: only the incident's own tenant's routes
        # match (NULL-tenant incidents -> NULL-tenant/legacy routes)
        routes = list(
            (
                await db.execute(
                    select(NotificationRoute).where(
                        NotificationRoute.enabled.is_(True),
                        NotificationRoute.tenant_id == incident.tenant_id,
                    )
                )
            ).scalars()
        )
        for route in routes:
            if severity_rank < SEVERITY_RANK.get(route.min_severity, 0):
                continue
            members = await group_member_users(db, route.group_id)
            targets = build_targets(members, route.channels or [])
            created_total += await create_notifications(db, incident, route.group_id, targets)
    await db.flush()
    return created_total


async def fan_out_to_group(db: AsyncSession, incident: Incident, group: Group) -> int:
    """Manual send: fan out to one group on both channels, route bypassed."""
    members = await group_member_users(db, group.id)
    targets = build_targets(members, ["telegram", "email"])
    return await create_notifications(db, incident, group.id, targets)
