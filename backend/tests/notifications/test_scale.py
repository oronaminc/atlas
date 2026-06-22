"""Phase 4 notification scale: per-incident dedup, priority ordering, single
global claim queue, pipelined sends, quota-defer visibility."""

from datetime import timedelta

from sqlalchemy import select

from app.models.alerting import AlertEvent
from app.models.delivery import Notification, NotificationSettings
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending, fan_out_to_group, severity_priority
from app.notifications.outbox import claim_batch
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    seed_group,
    seed_incident,
    seed_route,
    seed_user,
)

# --- per-incident dedup ---


async def test_many_alerts_one_notification_per_recipient(db):
    """10 alert events attached to one incident -> exactly ONE notification
    per (recipient, channel), not one per alert."""
    user = await seed_user(db, "u@x.io", chat_id="c1")
    group = await seed_group(db, "g", [user])
    await seed_route(db, group, min_severity="info", channels=["telegram"])
    incident = await seed_incident(db, severity="critical")
    for i in range(10):
        db.add(
            AlertEvent(
                fingerprint=f"fp{i}",
                source="am",
                name="HighCPU",
                severity="critical",
                status="firing",
                labels={},
                annotations={},
                starts_at=NOW,
                received_at=NOW,
                incident_id=incident.id,
            )
        )
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 1

    rows = (await db.execute(select(Notification))).scalars().all()
    assert len(rows) == 1
    assert rows[0].recipient_address == "c1"


async def test_refanout_is_idempotent(db):
    user = await seed_user(db, "u@x.io", chat_id="c1")
    group = await seed_group(db, "g", [user])
    incident = await seed_incident(db, severity="critical")
    await db.commit()

    first = await fan_out_to_group(db, incident, group)
    await db.commit()
    second = await fan_out_to_group(db, incident, group)
    await db.commit()
    # telegram + email = 2 targets first time, 0 the second
    assert first == 2 and second == 0
    assert (await db.execute(select(Notification))).scalars().all().__len__() == 2


# --- priority ---


async def test_priority_set_from_severity_at_fanout(db):
    for sev, expect in [("critical", 0), ("warning", 1), ("info", 2)]:
        assert severity_priority(sev) == expect
    user = await seed_user(db, "u@x.io", chat_id="c1")
    group = await seed_group(db, "g", [user])
    await seed_route(db, group, min_severity="info", channels=["telegram"])
    crit = await seed_incident(db, severity="critical", title="crit")
    info = await seed_incident(db, severity="info", title="info")
    info.group_key = "host=other"
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    by_addr = {
        n.incident_id: n.priority for n in (await db.execute(select(Notification))).scalars()
    }
    assert by_addr[crit.id] == 0
    assert by_addr[info.id] == 2


async def test_claim_orders_critical_before_info(db):
    """The global claim queue drains higher priority (critical) first."""
    users = [await seed_user(db, f"u{i}@x.io", chat_id=f"c{i}") for i in range(6)]
    await seed_group(db, "g", users)
    # 3 info incidents (older) + 3 critical (newer): priority must win over age
    for i in range(3):
        inc = await seed_incident(db, severity="info", title=f"info{i}")
        inc.group_key = f"host=i{i}"
        await db.flush()
        for u in users:
            db.add(
                Notification(
                    incident_id=inc.id,
                    channel="telegram",
                    recipient_user_id=u.id,
                    recipient_address=u.telegram_chat_id,
                    status="pending",
                    priority=2,
                    created_at=NOW - timedelta(hours=2),
                )
            )
    for i in range(3):
        inc = await seed_incident(db, severity="critical", title=f"crit{i}")
        inc.group_key = f"host=c{i}"
        await db.flush()
        for u in users:
            db.add(
                Notification(
                    incident_id=inc.id,
                    channel="telegram",
                    recipient_user_id=u.id,
                    recipient_address=u.telegram_chat_id,
                    status="pending",
                    priority=0,
                    created_at=NOW,
                )
            )
    await db.commit()

    batch = await claim_batch(db, worker_id="w", now=NOW, limit=10)
    assert len(batch) == 10
    # all claimed rows are the critical (priority 0) ones
    assert all(n.priority == 0 for n in batch)


# --- single global claim queue (multi-tenancy removed) ---


async def test_claim_fills_batch_up_to_limit(db):
    """The claim is a single global queue: a backlog larger than the limit
    yields exactly `limit` rows, ordered by (priority, created_at)."""
    inc = await seed_incident(db, title="a")
    await db.flush()
    for i in range(80):
        u = await seed_user(db, f"a{i}@x.io", chat_id=f"ca{i}")
        db.add(
            Notification(
                incident_id=inc.id,
                channel="telegram",
                recipient_user_id=u.id,
                recipient_address=f"ca{i}",
                status="pending",
                priority=1,
                created_at=NOW,
            )
        )
    await db.commit()
    batch = await claim_batch(db, worker_id="w", now=NOW, limit=50)
    assert len(batch) == 50  # claim caps at the limit; rest stay pending
    remaining = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.status == "pending", Notification.claimed_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining) == 30


# --- quota defer visibility + pipelined send ---


async def test_quota_defer_sets_reason_and_stays_pending(db):
    users = [await seed_user(db, f"u{i}@x.io", chat_id=f"c{i}") for i in range(5)]
    group = await seed_group(db, "g", users)
    await seed_route(db, group, min_severity="info", channels=["telegram"])
    await seed_incident(db, severity="critical")
    db.add(
        NotificationSettings(
            telegram_bot_token=None,
            telegram_rate_per_second=100,
            quota_group_per_hour=2,  # only 2 of 5 may send
            quota_global_per_day=1000,
        )
    )
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()

    channel = FakeChannel()
    result = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()

    assert int(result) == 2  # quota capped sends
    assert result.deferred == 3
    deferred = (
        (await db.execute(select(Notification).where(Notification.status == "pending")))
        .scalars()
        .all()
    )
    assert len(deferred) == 3
    assert all("quota: group" in (n.last_error or "") for n in deferred)
    assert all(n.retry_at is not None for n in deferred)


async def test_pipelined_send_marks_all_sent(db):
    users = [await seed_user(db, f"u{i}@x.io", chat_id=f"c{i}") for i in range(12)]
    group = await seed_group(db, "g", users)
    await seed_route(db, group, min_severity="info", channels=["telegram"])
    await seed_incident(db, severity="critical")
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()

    channel = FakeChannel()
    result = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    assert int(result) == 12
    assert len(channel.sent) == 12
    statuses = (await db.execute(select(Notification.status))).scalars().all()
    assert all(s == "sent" for s in statuses)
