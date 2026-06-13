"""Delivery pass: claim → quota → throttle → channel.send → mark.
Quota counting uses sent rows in PG (exact, shared across pods).

Tenancy: settings (bot token / rate / quotas), channels and the token
bucket are resolved PER TENANT from each notification row's tenant_id —
tenant A's bot token and quota are never used for tenant B. Tests and
single-tenant callers may still pass explicit `channels=`/`throttle=`
overrides, which apply to every row in the pass.
"""

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import instruments
from app.core.config import settings as app_settings
from app.models.alerting import Incident
from app.models.delivery import Notification, NotificationSettings
from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.registry import build_channels
from app.notifications.outbox import claim_batch, defer, mark_failed, mark_sent
from app.notifications.settings import get_notification_settings
from app.notifications.throttle import TokenBucket

logger = logging.getLogger(__name__)


class DeliveryResult(int):
    """int == successful-send count (back-compat with `sent == N` asserts),
    plus claim metadata the worker needs to decide whether to loop again."""

    claimed: int
    deferred: int
    was_full: bool

    def __new__(cls, sent: int, *, claimed: int, deferred: int, was_full: bool):
        obj = super().__new__(cls, sent)
        obj.claimed = claimed
        obj.deferred = deferred
        obj.was_full = was_full
        return obj


def _send_concurrency(rate_per_second: float) -> int:
    """Fill the RTT pipe: ceil(rate*RTT)+4, capped. The TokenBucket still
    enforces the sustained rate; this just removes the serial bottleneck."""
    rtt = app_settings.SEND_RTT_ESTIMATE_SECONDS
    return max(1, min(app_settings.SEND_CONCURRENCY_CAP, math.ceil(rate_per_second * rtt) + 4))


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


async def _resolve_context(db, n, *, channels, throttle, throttles) -> "_TenantContext":
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
    return _TenantContext(settings_row, tenant_channels, bucket)


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
) -> DeliveryResult:
    """One delivery pass. Per tenant: quota-gate + reserve SYNCHRONOUSLY (so
    concurrent sends can't slip past the same quota), then pipeline the actual
    channel.send calls with a bounded gather to saturate the per-tenant rate
    budget, then apply DB writes serially (one AsyncSession is not concurrency-
    safe). `throttles` (tenant_id -> TokenBucket) persists across passes when
    the caller keeps the dict alive.

    Returns DeliveryResult (==sent count) with claimed/deferred/was_full."""
    batch = await claim_batch(
        db, worker_id=worker_id, now=now, lease_seconds=lease_seconds, limit=limit
    )

    # group claimed rows by tenant (claim already ordered by priority,created_at)
    by_tenant: dict[uuid.UUID | None, list[Notification]] = {}
    for n in batch:
        by_tenant.setdefault(n.tenant_id, []).append(n)

    sent = 0
    deferred = 0

    for tenant_id, rows in by_tenant.items():
        ctx = await _resolve_context(
            db, rows[0], channels=channels, throttle=throttle, throttles=throttles
        )
        if ctx.global_sent is None:
            ctx.global_sent = await _sent_count_since(
                db, now - timedelta(days=1), tenant_id=tenant_id
            )

        # --- phase 1: quota gate + RESERVE synchronously (no await between
        # check and reserve, so concurrent dispatch can't double-spend quota)
        to_send: list[tuple[Notification, NotificationChannel]] = []
        for n in rows:
            if ctx.global_sent >= ctx.settings.quota_global_per_day:
                await defer(
                    db,
                    n,
                    retry_at=now + timedelta(days=1),
                    reason=f"quota: global {ctx.settings.quota_global_per_day}/day reached",
                )
                instruments.notifications_deferred.inc(reason="quota_global")
                deferred += 1
                continue
            if n.group_id is not None:
                if n.group_id not in ctx.group_sent:
                    ctx.group_sent[n.group_id] = await _sent_count_since(
                        db, now - timedelta(hours=1), group_id=n.group_id, tenant_id=tenant_id
                    )
                if ctx.group_sent[n.group_id] >= ctx.settings.quota_group_per_hour:
                    await defer(
                        db,
                        n,
                        retry_at=now + timedelta(hours=1),
                        reason=f"quota: group {ctx.settings.quota_group_per_hour}/h reached",
                    )
                    instruments.notifications_deferred.inc(reason="quota_group")
                    deferred += 1
                    continue
            channel = ctx.channels.get(n.channel)
            if channel is None:
                await mark_failed(db, n, f"channel not configured: {n.channel}", now=now)
                continue
            # reserve quota slots now
            ctx.global_sent += 1
            if n.group_id is not None:
                ctx.group_sent[n.group_id] += 1
            to_send.append((n, channel))

        if not to_send:
            continue

        # --- phase 2: pipeline the network sends (bounded), DB-free
        sem = asyncio.Semaphore(_send_concurrency(ctx.settings.telegram_rate_per_second))

        async def _do_send(n, channel, bucket=ctx.throttle, sem=sem):
            async with sem:
                if bucket is not None:
                    await bucket.acquire(n.recipient_address)
                t0 = time.perf_counter()
                try:
                    await channel.send(n.recipient_address, render_message(n.incident))
                    instruments.notification_send_seconds.observe(
                        time.perf_counter() - t0, channel=n.channel
                    )
                    return n, None
                except Exception as exc:  # noqa: BLE001
                    return n, exc

        results = await asyncio.gather(*(_do_send(n, ch) for n, ch in to_send))

        # --- phase 3: apply outcomes serially (single session); release the
        # quota reservation for any send that failed
        for n, err in results:
            if err is None:
                await mark_sent(db, n, now=now)
                instruments.notifications_sent.inc(channel=n.channel)
                sent += 1
            else:
                ctx.global_sent -= 1
                if n.group_id is not None:
                    ctx.group_sent[n.group_id] -= 1
                await mark_failed(db, n, str(err), now=now)
                instruments.notifications_failed.inc(channel=n.channel)
                if n.status == "dead":
                    instruments.notifications_dead.inc(channel=n.channel)

    return DeliveryResult(sent, claimed=len(batch), deferred=deferred, was_full=len(batch) >= limit)
