"""Delivery pass: claim → quota → throttle → channel.send → mark.
Quota counting uses sent rows in PG (exact, shared across pods)."""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import Incident
from app.models.delivery import Notification
from app.notifications.channels.base import NotificationChannel
from app.notifications.outbox import claim_batch, defer, mark_failed, mark_sent
from app.notifications.settings import get_notification_settings

logger = logging.getLogger(__name__)


def render_message(incident: Incident) -> str:
    """First line doubles as the email subject."""
    return (
        f"[Atlas] [{incident.severity}] {incident.title}\n"
        f"status: {incident.status.value}\n"
        f"alerts: {incident.alert_count}\n"
        f"first seen: {incident.first_seen.isoformat()}"
    )


async def _sent_count_since(
    db: AsyncSession, since: datetime, group_id: uuid.UUID | None = None
) -> int:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.status == "sent", Notification.sent_at > since)
    )
    if group_id is not None:
        stmt = stmt.where(Notification.group_id == group_id)
    return (await db.execute(stmt)).scalar_one()


async def deliver_once(
    db: AsyncSession,
    *,
    channels: dict[str, NotificationChannel],
    worker_id: str,
    now: datetime,
    throttle=None,
    lease_seconds: int = 60,
    limit: int = 50,
) -> int:
    """One delivery pass; returns the number of successful sends."""
    settings_row = await get_notification_settings(db)
    batch = await claim_batch(
        db, worker_id=worker_id, now=now, lease_seconds=lease_seconds, limit=limit
    )

    # in-pass counters on top of the DB window counts
    global_sent = await _sent_count_since(db, now - timedelta(days=1))
    group_sent: dict[uuid.UUID, int] = {}
    sent = 0

    for n in batch:
        if global_sent >= settings_row.quota_global_per_day:
            await defer(db, n, retry_at=now + timedelta(days=1))
            continue
        if n.group_id is not None:
            if n.group_id not in group_sent:
                group_sent[n.group_id] = await _sent_count_since(
                    db, now - timedelta(hours=1), group_id=n.group_id
                )
            if group_sent[n.group_id] >= settings_row.quota_group_per_hour:
                await defer(db, n, retry_at=now + timedelta(hours=1))
                continue

        channel = channels.get(n.channel)
        if channel is None:
            await mark_failed(db, n, f"channel not configured: {n.channel}", now=now)
            continue

        if throttle is not None:
            await throttle.acquire(n.recipient_address)
        try:
            await channel.send(n.recipient_address, render_message(n.incident))
        except Exception as exc:
            await mark_failed(db, n, str(exc), now=now)
            continue
        await mark_sent(db, n, now=now)
        sent += 1
        global_sent += 1
        if n.group_id is not None:
            group_sent[n.group_id] += 1
    return sent
