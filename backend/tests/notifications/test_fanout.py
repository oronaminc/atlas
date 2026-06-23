"""Fan-out: incident → l2 → groups → each group's channels (toggle-gated)."""

import pytest
from sqlalchemy import select

from app.models.alerting import Incident, IncidentEvent
from app.models.delivery import Notification
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_group_channel,
    seed_incident,
    seed_route,
)

pytestmark = pytest.mark.asyncio


async def rows(db) -> list[Notification]:
    return list((await db.execute(select(Notification))).scalars())


async def test_fanout_creates_row_per_group_channel(db):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="bot", chat_id="111")
    await seed_group_channel(db, group, "telegram", bot_token="bot", chat_id="222")
    incident = await seed_incident(db, channels=["telegram"])
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 2
    notifications = await rows(db)
    assert {n.recipient_address for n in notifications} == {"111", "222"}
    assert all(n.channel == "telegram" and n.status == "pending" for n in notifications)
    assert all(n.incident_id == incident.id and n.group_channel_id for n in notifications)
    assert (await db.get(Incident, incident.id)).notified_at is not None


async def test_toggle_gates_channel_type(db):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="111")
    await seed_group_channel(db, group, "email", email="ops@x.io")
    await seed_incident(db, channels=["email"])  # telegram toggle OFF
    await db.commit()
    await fan_out_pending(db, now=NOW)
    await db.commit()
    notifications = await rows(db)
    assert len(notifications) == 1 and notifications[0].channel == "email"


async def test_toggles_off_creates_nothing_but_marks_notified(db):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="111")
    incident = await seed_incident(db, channels=[])
    await db.commit()
    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 0 and await rows(db) == []
    assert (await db.get(Incident, incident.id)).notified_at is not None


async def test_no_mapping_no_recipients_but_marks_notified(db):
    # decision I: toggles on but no group-channel maps the incident's l2
    incident = await seed_incident(db, channels=["telegram"])
    await db.commit()
    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 0 and await rows(db) == []
    assert (await db.get(Incident, incident.id)).notified_at is not None
    kinds = {
        e.kind
        for e in (await db.execute(select(IncidentEvent))).scalars()
        if e.incident_id == incident.id
    }
    assert "no_recipients" in kinds


async def test_oncall_channel_one_row_per_group(db):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "oncall", webhook_url="https://hook")
    await seed_incident(db, channels=["oncall"])
    await db.commit()
    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    notifications = await rows(db)
    assert created == 1 and notifications[0].channel == "oncall"
    assert notifications[0].recipient_user_id is None


async def test_refanout_is_idempotent(db):
    group = await seed_group(db, "oncall", [])
    await seed_route(db, group)
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="111")
    await seed_incident(db, channels=["telegram"])
    await db.commit()
    first = await fan_out_pending(db, now=NOW)
    await db.commit()
    second = await fan_out_pending(db, now=NOW)  # notified_at CAS -> nothing
    await db.commit()
    assert first == 1 and second == 0 and len(await rows(db)) == 1
