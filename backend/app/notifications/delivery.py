"""Delivery pass: claim → quota → throttle → channel.send → mark.
Quota counting uses sent rows in PG (exact, shared across pods).

Tenancy: settings (bot token / rate / quotas), channels and the token
bucket are resolved PER TENANT from each notification row's tenant_id —
tenant A's bot token and quota are never used for tenant B. Tests and
single-tenant callers may still pass explicit `channels=`/`throttle=`
overrides, which apply to every row in the pass.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerting import Incident
from app.models.delivery import Notification, NotificationSettings
from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.registry import build_channels
from app.notifications.outbox import claim_batch, defer, mark_failed, mark_sent
from app.notifications.settings import get_notification_settings
from app.notifications.throttle import TokenBucket

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
    db: AsyncSession,
    since: datetime,
    group_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.status == "sent",
            Notification.sent_at > since,
            Notification.tenant_id == tenant_id,
        )
    )
    if group_id is not None:
        stmt = stmt.where(Notification.group_id == group_id)
    return (await db.execute(stmt)).scalar_one()


class _TenantContext:
    """Per-tenant settings/channels/throttle/quota counters for one pass."""

    def __init__(self, settings_row: NotificationSettings, channels, throttle):
        self.settings = settings_row
        self.channels = channels
        self.throttle = throttle
        self.global_sent: int | None = None
        self.group_sent: dict[uuid.UUID, int] = {}


async def deliver_once(
    db: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    channels: dict[str, NotificationChannel] | None = None,
    throttle=None,
    throttles: dict | None = None,
    lease_seconds: int = 60,
    limit: int = 50,
) -> int:
    """One delivery pass; returns the number of successful sends.
    `throttles` (tenant_id -> TokenBucket) persists across passes when the
    caller (notification worker) keeps the dict alive."""
    batch = await claim_batch(
        db, worker_id=worker_id, now=now, lease_seconds=lease_seconds, limit=limit
    )

    contexts: dict[uuid.UUID | None, _TenantContext] = {}
    sent = 0

    for n in batch:
        ctx = contexts.get(n.tenant_id)
        if ctx is None:
            settings_row = await get_notification_settings(db, n.tenant_id)
            tenant_channels = channels if channels is not None else build_channels(settings_row)
            if throttle is not None:
                bucket = throttle
            elif throttles is not None:
                bucket = throttles.get(n.tenant_id)
                if bucket is None or getattr(bucket, "_rate", None) != float(
                    max(settings_row.telegram_rate_per_second, 0.001)
                ):
                    bucket = TokenBucket(rate_per_second=settings_row.telegram_rate_per_second)
                    throttles[n.tenant_id] = bucket
            else:
                bucket = None
            ctx = contexts[n.tenant_id] = _TenantContext(settings_row, tenant_channels, bucket)

        if ctx.global_sent is None:
            ctx.global_sent = await _sent_count_since(
                db, now - timedelta(days=1), tenant_id=n.tenant_id
            )
        if ctx.global_sent >= ctx.settings.quota_global_per_day:
            await defer(db, n, retry_at=now + timedelta(days=1))
            continue
        if n.group_id is not None:
            if n.group_id not in ctx.group_sent:
                ctx.group_sent[n.group_id] = await _sent_count_since(
                    db, now - timedelta(hours=1), group_id=n.group_id, tenant_id=n.tenant_id
                )
            if ctx.group_sent[n.group_id] >= ctx.settings.quota_group_per_hour:
                await defer(db, n, retry_at=now + timedelta(hours=1))
                continue

        channel = ctx.channels.get(n.channel)
        if channel is None:
            await mark_failed(db, n, f"channel not configured: {n.channel}", now=now)
            continue

        if ctx.throttle is not None:
            await ctx.throttle.acquire(n.recipient_address)
        try:
            await channel.send(n.recipient_address, render_message(n.incident))
        except Exception as exc:
            await mark_failed(db, n, str(exc), now=now)
            continue
        await mark_sent(db, n, now=now)
        sent += 1
        ctx.global_sent += 1
        if n.group_id is not None:
            ctx.group_sent[n.group_id] += 1
    return sent
