"""Notification fan-out under storm.

Seeds: one group with --recipients members (telegram targets), a route,
--incidents un-notified critical incidents. Then runs the REAL
fan_out_pending + deliver_once code in-process — exactly the notification
worker loop, except TelegramChannel points at the local stub and the loop
has no 5s sleep (measures the pipeline's own ceiling; the production
worker adds sleep(5) on top, reported separately).

Requires: telegram_stub running, DATABASE_URL set to the load PG.

Usage:
    DATABASE_URL=postgresql+asyncpg://atlas:atlas@127.0.0.1:5432/atlas \
      uv run python -m loadtest.fanout_storm --recipients 300 --incidents 10
"""

import argparse
import asyncio
import time
import uuid

from sqlalchemy import func, select, text

from app.core.security import hash_password
from app.db import async_session_factory
from app.models import Group, User, UserGroup
from app.models.alerting import Incident, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import Notification, NotificationRoute
from app.notifications.channels.telegram import TelegramChannel
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending
from app.notifications.throttle import TokenBucket

STUB = "http://127.0.0.1:18082"


async def seed(recipients: int, incidents: int) -> None:
    async with async_session_factory() as db:
        group = Group(name=f"storm-{uuid.uuid4().hex[:6]}")
        db.add(group)
        await db.flush()
        for i in range(recipients):
            user = User(
                email=f"storm-{group.name}-{i}@example.com",
                username=f"storm-{group.name}-{i}",
                hashed_password=hash_password("password123"),
                telegram_chat_id=str(100000 + i),
            )
            db.add(user)
            await db.flush()
            db.add(UserGroup(user_id=user.id, group_id=group.id))
        db.add(
            NotificationRoute(
                group_id=group.id, min_severity="warning", channels=["telegram"], enabled=True
            )
        )
        # quotas must not cap the measurement; rate stays at the configured 25/s.
        # get_notification_settings creates the row if missing — UPDATE alone
        # silently no-ops on a fresh DB and the default quota (30/group/h)
        # freezes the test at exactly 30 sends.
        from app.notifications.settings import get_notification_settings

        settings_row = await get_notification_settings(db)
        settings_row.quota_group_per_hour = 1_000_000
        settings_row.quota_global_per_day = 1_000_000
        # pre-existing incidents must not fan out to this route too (routes
        # are global: every enabled route matches every un-notified incident)
        await db.execute(text("UPDATE incidents SET notified_at = now() WHERE notified_at IS NULL"))

        now = utcnow()
        for i in range(incidents):
            db.add(
                Incident(
                    title=f"storm incident {i}",
                    status=IncidentStatus.open,
                    severity="critical",
                    group_key=f"host=storm-{i:03d}",
                    first_seen=now,
                    last_seen=now,
                    alert_count=1,
                )
            )
        await db.commit()
    print(f"seeded {recipients} recipients x telegram, {incidents} incidents")


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
            sent_total += sent
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
