"""Notification fan-out under storm.

Seeds: one group mapped to an l2 service code, with --recipients telegram
GroupChannels (distinct chat-ids), and --incidents un-notified critical
incidents carrying that l2. Then runs the REAL fan_out_pending + deliver_once
in-process — exactly the notification worker loop, except TelegramChannel
points at the local stub and the loop has no 5s sleep (measures the pipeline's
own ceiling; the production worker adds sleep(5) on top, reported separately).

Quotas/rate are ENV now (no notification_settings row). To avoid capping the
measurement, export high quotas before running:

    NOTIFY_QUOTA_GROUP_PER_HOUR=1000000 NOTIFY_QUOTA_GLOBAL_PER_DAY=1000000 \
    DATABASE_URL=postgresql+asyncpg://atlas:atlas@127.0.0.1:5432/atlas \
      uv run python -m loadtest.fanout_storm --recipients 300 --incidents 10

Requires: telegram_stub running, DATABASE_URL set to the load PG.
"""

import argparse
import asyncio
import time
import uuid

from sqlalchemy import func, select, text

from app.core.security import encrypt_secret
from app.db import async_session_factory
from app.models import Group
from app.models.alerting import Incident, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import GroupChannel, Notification
from app.models.group import GroupServiceCode
from app.notifications.channels.telegram import TelegramChannel
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.notifications.throttle import TokenBucket

STUB = "http://127.0.0.1:18082"


async def seed(recipients: int, incidents: int) -> str:
    """Returns the l2 code the incidents + group share."""
    l2 = f"L2-storm-{uuid.uuid4().hex[:6]}"
    async with async_session_factory() as db:
        group = Group(name=f"storm-{uuid.uuid4().hex[:6]}")
        db.add(group)
        await db.flush()
        db.add(GroupServiceCode(group_id=group.id, cmdb_service_l2_code=l2))
        # recipients = N telegram channels under the group (distinct chat-ids).
        # fanout emits one notification per (incident, channel) -> recipients x incidents.
        for i in range(recipients):
            db.add(
                GroupChannel(
                    group_id=group.id,
                    channel="telegram",
                    enabled=True,
                    chat_id=str(100000 + i),
                    bot_token=encrypt_secret("stub-bot-token"),
                )
            )
        # pre-existing incidents must not fan out too (fanout matches every
        # un-notified incident whose l2 maps to a group).
        await db.execute(text("UPDATE incidents SET notified_at = now() WHERE notified_at IS NULL"))

        now = utcnow()
        for i in range(incidents):
            db.add(
                Incident(
                    title=f"storm incident {i}",
                    status=IncidentStatus.open,
                    severity="critical",
                    group_key=l2,
                    cmdb_service_l2_code=l2,
                    first_seen=now,
                    last_seen=now,
                    alert_count=1,
                )
            )
        await db.commit()
    print(f"seeded {recipients} telegram channels on {l2}, {incidents} incidents")
    return l2


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipients", type=int, default=300)
    ap.add_argument("--incidents", type=int, default=10)
    ap.add_argument(
        "--rate", type=float, default=25.0, help="telegram rate/s (default = prod setting)"
    )
    ap.add_argument("--watch", type=float, default=300)
    args = ap.parse_args()

    await seed(args.recipients, args.incidents)

    # Override the channel so sends hit the local stub, not real Telegram.
    channels = {"telegram": TelegramChannel(token="stub", api_base=STUB)}
    throttle = TokenBucket(rate_per_second=args.rate)
    expected = args.recipients * args.incidents

    t0 = time.monotonic()
    samples = []
    fanned = sent_total = 0
    while time.monotonic() - t0 < args.watch:
        async with async_session_factory() as db:
            fanned += await fan_out_pending(db, now=utcnow())
            sent = await deliver_once(
                db,
                channels=channels,
                worker_id="loadtest",
                now=utcnow(),
                throttle=throttle,
            )
            await db.commit()
            sent_total += int(sent)  # DeliveryResult is an int (successful-send count)
            pending = (
                await db.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.status == "pending")
                )
            ).scalar_one()
        samples.append((time.monotonic() - t0, pending, sent_total))
        if sent_total >= expected and pending == 0:
            break

    print("t(s)  pending  sent_total")
    for t, p, s in samples[:: max(1, len(samples) // 25)]:
        print(f"{t:5.1f}  {p:>7}  {s:>10}")
    elapsed = samples[-1][0]
    print(
        f"\n{sent_total}/{expected} sent in {elapsed:.1f}s = {sent_total / elapsed:.1f}/s "
        f"(throttle set to {args.rate}/s)"
    )
    print(
        "NOTE: production notification_worker adds sleep(5) per iteration "
        "-> effective ceiling = 50 sends / (5s + batch_time) regardless of throttle"
    )


if __name__ == "__main__":
    asyncio.run(main())
