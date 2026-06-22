"""Delivery pass: claim → quota → throttle → channel.send → mark.
Quota counting uses sent rows in PG (exact, shared across pods).

Settings (bot token / rate / quotas), channels and the token bucket are the
single global config. Tests and callers may pass explicit `channels=`/
`throttle=` overrides, which apply to every row in the pass."""

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
from app.models.delivery import Notification
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
    worker_id: str,
    now: datetime,
    channels: dict[str, NotificationChannel] | None = None,
    throttle=None,
    throttles: dict | None = None,
    lease_seconds: int = 60,
    limit: int = 50,
) -> DeliveryResult:
    """One delivery pass. Quota-gate + reserve SYNCHRONOUSLY (so concurrent
    sends can't slip past the same quota), then pipeline the actual channel.send
    calls with a bounded gather to saturate the rate budget, then apply DB
    writes serially (one AsyncSession is not concurrency-safe).

    Returns DeliveryResult (==sent count) with claimed/deferred/was_full."""
    batch = await claim_batch(
        db, worker_id=worker_id, now=now, lease_seconds=lease_seconds, limit=limit
    )
    if not batch:
        return DeliveryResult(0, claimed=0, deferred=0, was_full=False)

    settings_row = await get_notification_settings(db)
    active_channels = channels if channels is not None else build_channels(settings_row)
    if throttle is not None:
        bucket = throttle
    elif throttles is not None:
        bucket = throttles.get("_global")
        if bucket is None or getattr(bucket, "_rate", None) != float(
            max(settings_row.telegram_rate_per_second, 0.001)
        ):
            bucket = TokenBucket(rate_per_second=settings_row.telegram_rate_per_second)
            throttles["_global"] = bucket
    else:
        bucket = None

    sent = 0
    deferred = 0
    global_sent = await _sent_count_since(db, now - timedelta(days=1))
    group_sent: dict[uuid.UUID, int] = {}

    # --- phase 1: quota gate + RESERVE synchronously (no await between check
    # and reserve, so concurrent dispatch can't double-spend quota)
    to_send: list[tuple[Notification, NotificationChannel]] = []
    for n in batch:
        if global_sent >= settings_row.quota_global_per_day:
            await defer(
                db,
                n,
                retry_at=now + timedelta(days=1),
                reason=f"quota: global {settings_row.quota_global_per_day}/day reached",
            )
            instruments.notifications_deferred.inc(reason="quota_global")
            deferred += 1
            continue
        if n.group_id is not None:
            if n.group_id not in group_sent:
                group_sent[n.group_id] = await _sent_count_since(
                    db, now - timedelta(hours=1), group_id=n.group_id
                )
            if group_sent[n.group_id] >= settings_row.quota_group_per_hour:
                await defer(
                    db,
                    n,
                    retry_at=now + timedelta(hours=1),
                    reason=f"quota: group {settings_row.quota_group_per_hour}/h reached",
                )
                instruments.notifications_deferred.inc(reason="quota_group")
                deferred += 1
                continue
        channel = active_channels.get(n.channel)
        if channel is None:
            await mark_failed(db, n, f"channel not configured: {n.channel}", now=now)
            continue
        global_sent += 1
        if n.group_id is not None:
            group_sent[n.group_id] += 1
        to_send.append((n, channel))

    if not to_send:
        return DeliveryResult(
            sent, claimed=len(batch), deferred=deferred, was_full=len(batch) >= limit
        )

    # --- phase 2: pipeline the network sends (bounded), DB-free
    sem = asyncio.Semaphore(_send_concurrency(settings_row.telegram_rate_per_second))

    async def _do_send(n, channel, b=bucket, sem=sem):
        async with sem:
            if b is not None:
                await b.acquire(n.recipient_address)
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

    # --- phase 3: apply outcomes serially (single session); release the quota
    # reservation for any send that failed
    for n, err in results:
        if err is None:
            await mark_sent(db, n, now=now)
            instruments.notifications_sent.inc(channel=n.channel)
            sent += 1
        else:
            global_sent -= 1
            if n.group_id is not None:
                group_sent[n.group_id] -= 1
            await mark_failed(db, n, str(err), now=now)
            instruments.notifications_failed.inc(channel=n.channel)
            if n.status == "dead":
                instruments.notifications_dead.inc(channel=n.channel)

    return DeliveryResult(sent, claimed=len(batch), deferred=deferred, was_full=len(batch) >= limit)
