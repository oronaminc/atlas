"""Notification scale: per-incident dedup, priority ordering, single global
claim queue, quota-defer visibility, pipelined send."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.alerting import AlertEvent
from app.models.delivery import Notification
from app.notifications.delivery import deliver_once
from app.notifications.fanout import fan_out_pending, fan_out_to_group, severity_priority
from app.notifications.outbox import claim_batch
from tests.notifications.helpers import (
    NOW,
    FakeChannel,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

pytestmark = pytest.mark.asyncio


async def test_many_alerts_one_notification_per_channel(db):
    """10 alerts on one incident -> ONE notification per group channel, not per alert."""
    group = await seed_group(db, "g", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="c1")
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
    assert await fan_out_pending(db, now=NOW) == 1
    await db.commit()
    rows = (await db.execute(select(Notification))).scalars().all()
    assert len(rows) == 1 and rows[0].recipient_address == "c1"


async def test_fan_out_to_group_idempotent(db):
    group = await seed_group(db, "g", [])
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="c1")
    await seed_group_channel(db, group, "email", email="ops@x.io")
    incident = await seed_incident(db, severity="critical")
    await db.commit()
    first = await fan_out_to_group(db, incident, group)
    await db.commit()
    second = await fan_out_to_group(db, incident, group)
    await db.commit()
    assert first == 2 and second == 0  # telegram + email once
    assert len((await db.execute(select(Notification))).scalars().all()) == 2


async def test_priority_from_severity(db):
    for sev, expect in [("critical", 0), ("warning", 1), ("info", 2)]:
        assert severity_priority(sev) == expect
    group = await seed_group(db, "g", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="c1")
    crit = await seed_incident(db, severity="critical", title="crit")
    info = await seed_incident(db, severity="info", title="info")
    info.group_key = "host=other"
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    pr = {n.incident_id: n.priority for n in (await db.execute(select(Notification))).scalars()}
    assert pr[crit.id] == 0 and pr[info.id] == 2


async def test_claim_orders_critical_before_info(db):
    inc = await seed_incident(db, title="x")
    await db.flush()
    for i in range(3):
        db.add(
            Notification(
                incident_id=inc.id,
                channel="telegram",
                recipient_address=f"i{i}",
                status="pending",
                priority=2,
                created_at=NOW - timedelta(hours=2),
            )
        )
    for i in range(3):
        db.add(
            Notification(
                incident_id=inc.id,
                channel="telegram",
                recipient_address=f"c{i}",
                status="pending",
                priority=0,
                created_at=NOW,
            )
        )
    await db.commit()
    batch = await claim_batch(db, worker_id="w", now=NOW, limit=3)
    assert len(batch) == 3 and all(n.priority == 0 for n in batch)


async def test_claim_fills_batch_up_to_limit(db):
    inc = await seed_incident(db, title="a")
    await db.flush()
    for i in range(80):
        db.add(
            Notification(
                incident_id=inc.id,
                channel="telegram",
                recipient_address=f"ca{i}",
                status="pending",
                priority=1,
                created_at=NOW,
            )
        )
    await db.commit()
    batch = await claim_batch(db, worker_id="w", now=NOW, limit=50)
    assert len(batch) == 50
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


async def test_quota_defer_sets_reason(db, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_QUOTA_GROUP_PER_HOUR", 2)
    group = await seed_group(db, "g", [])
    await seed_route(db, group)
    for i in range(5):
        await seed_group_channel(db, group, "telegram", bot_token="b", chat_id=f"c{i}")
    await seed_incident(db, severity="critical")
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    result = await deliver_once(db, channels={"telegram": FakeChannel()}, worker_id="w", now=NOW)
    await db.commit()
    assert int(result) == 2 and result.deferred == 3
    deferred = (
        (await db.execute(select(Notification).where(Notification.status == "pending")))
        .scalars()
        .all()
    )
    assert len(deferred) == 3 and all("quota: group" in (n.last_error or "") for n in deferred)


async def test_pipelined_send_marks_all_sent(db):
    group = await seed_group(db, "g", [])
    await seed_route(db, group)
    for i in range(12):
        await seed_group_channel(db, group, "telegram", bot_token="b", chat_id=f"c{i}")
    await seed_incident(db, severity="critical")
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    channel = FakeChannel()
    result = await deliver_once(db, channels={"telegram": channel}, worker_id="w", now=NOW)
    await db.commit()
    assert int(result) == 12 and len(channel.sent) == 12
    assert all(s == "sent" for s in (await db.execute(select(Notification.status))).scalars().all())
