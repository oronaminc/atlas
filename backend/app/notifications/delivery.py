"""Delivery pass: claim → quota → throttle → channel.send → mark.

Each notification is sent through ITS group's channel (group_channels: the
group's own telegram bot / email / oncall webhook), resolved from
group_channel_id at send time. Rate/quota/soft-cap are global infra guards from
env (per-group business config is the channel set, not the limits). The
TokenBucket is keyed per group-channel so each group's bot has its own rate
budget. Tests/callers may pass `channels=`/`throttle=` overrides.
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
from app.models.delivery import GroupChannel, Notification
from app.notifications.channels.base import NotificationChannel
from app.notifications.channels.registry import channel_for
from app.notifications.outbox import claim_batch, defer, mark_failed, mark_sent
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


async def _resolve_channels(
    db: AsyncSession, batch: list[Notification], override: dict[str, NotificationChannel] | None
) -> dict[uuid.UUID, NotificationChannel | None]:
    """Per-notification channel instance. Override (tests) wins; otherwise build
    each from its group_channel's own secrets."""
    out: dict[uuid.UUID, NotificationChannel | None] = {}
    if override is not None:
        return {n.id: override.get(n.channel) for n in batch}
    gc_ids = {n.group_channel_id for n in batch if n.group_channel_id}
    gcs = {}
    if gc_ids:
        gcs = {
            gc.id: gc
            for gc in (
                await db.execute(select(GroupChannel).where(GroupChannel.id.in_(gc_ids)))
            ).scalars()
        }
    for n in batch:
        gc = gcs.get(n.group_channel_id)
        out[n.id] = channel_for(gc) if gc is not None else None
    return out


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
    """One delivery pass. Quota-gate + reserve synchronously, pipeline the sends
    (bounded gather), then apply DB writes serially. Returns DeliveryResult."""
    batch = await claim_batch(
        db, worker_id=worker_id, now=now, lease_seconds=lease_seconds, limit=limit
    )
    if not batch:
        return DeliveryResult(0, claimed=0, deferred=0, was_full=False)

    rate = app_settings.NOTIFY_RATE_PER_SECOND
    quota_day = app_settings.NOTIFY_QUOTA_GLOBAL_PER_DAY
    quota_hour = app_settings.NOTIFY_QUOTA_GROUP_PER_HOUR
    chan_for_id = await _resolve_channels(db, batch, channels)

    def bucket_for(n: Notification):
        if throttle is not None:
            return throttle
        if throttles is None:
            return None
        key = str(n.group_channel_id or "_global")
        b = throttles.get(key)
        if b is None:
            b = TokenBucket(rate_per_second=rate)
            throttles[key] = b
        return b

    sent = 0
    deferred = 0
    global_sent = await _sent_count_since(db, now - timedelta(days=1))
    group_sent: dict[uuid.UUID, int] = {}

    # --- phase 1: quota gate + RESERVE synchronously
    to_send: list[tuple[Notification, NotificationChannel]] = []
    for n in batch:
        if global_sent >= quota_day:
            await defer(
                db,
                n,
                retry_at=now + timedelta(days=1),
                reason=f"quota: global {quota_day}/day reached",
            )
            instruments.notifications_deferred.inc(reason="quota_global")
            deferred += 1
            continue
        if n.group_id is not None:
            if n.group_id not in group_sent:
                group_sent[n.group_id] = await _sent_count_since(
                    db, now - timedelta(hours=1), group_id=n.group_id
                )
            if group_sent[n.group_id] >= quota_hour:
                await defer(
                    db,
                    n,
                    retry_at=now + timedelta(hours=1),
                    reason=f"quota: group {quota_hour}/h reached",
                )
                instruments.notifications_deferred.inc(reason="quota_group")
                deferred += 1
                continue
        channel = chan_for_id.get(n.id)
        if channel is None:
            await mark_failed(db, n, f"no channel configured for {n.channel}", now=now)
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
    sem = asyncio.Semaphore(_send_concurrency(rate))

    async def _do_send(n, channel, sem=sem):
        async with sem:
            b = bucket_for(n)
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

    # --- phase 3: apply outcomes serially; release the quota reservation on fail
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
