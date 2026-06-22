"""Fan-out: incident → route match → notification rows (persisted intent)."""

from sqlalchemy import select

from app.models.alerting import Incident
from app.models.delivery import Notification
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_incident,
    seed_route,
    seed_user,
)


async def rows(db) -> list[Notification]:
    return list((await db.execute(select(Notification))).scalars())


async def test_fanout_creates_rows_per_member_with_chat_id(db):
    u1 = await seed_user(db, "a@example.com", chat_id="111")
    u2 = await seed_user(db, "b@example.com", chat_id="222")
    group = await seed_group(db, "oncall", [u1, u2])
    await seed_route(db, group, min_severity="warning", channels=["telegram"])
    incident = await seed_incident(db, severity="critical")
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()

    assert created == 2
    notifications = await rows(db)
    assert {n.recipient_address for n in notifications} == {"111", "222"}
    assert all(n.channel == "telegram" and n.status == "pending" for n in notifications)
    assert all(n.incident_id == incident.id for n in notifications)
    assert (await db.get(Incident, incident.id)).notified_at is not None


async def test_member_without_chat_id_skipped_for_telegram_but_gets_email(db):
    with_chat = await seed_user(db, "a@example.com", chat_id="111")
    without_chat = await seed_user(db, "b@example.com", chat_id=None)
    group = await seed_group(db, "oncall", [with_chat, without_chat])
    await seed_route(db, group)
    await seed_incident(db, channels=["telegram", "email"])  # channels = incident toggles
    await db.commit()

    await fan_out_pending(db, now=NOW)
    await db.commit()

    notifications = await rows(db)
    telegram = [n for n in notifications if n.channel == "telegram"]
    email = [n for n in notifications if n.channel == "email"]
    assert len(telegram) == 1 and telegram[0].recipient_address == "111"
    assert {n.recipient_address for n in email} == {"a@example.com", "b@example.com"}


async def test_toggles_off_creates_nothing_but_marks_notified(db):
    # IMP: every channel toggle off = effectively muted
    user = await seed_user(db, "a@example.com", chat_id="111")
    group = await seed_group(db, "oncall", [user])
    await seed_route(db, group)
    incident = await seed_incident(db, channels=[])
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()

    assert created == 0 and await rows(db) == []
    assert (await db.get(Incident, incident.id)).notified_at is not None


async def test_no_l2_mapping_no_recipients_but_marks_notified(db):
    # IMP decision I: channels on, but no user-group maps the incident's l2
    from app.models.alerting import IncidentEvent

    await seed_user(db, "a@example.com", chat_id="111")  # exists, but no group maps l2
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


async def test_oncall_creates_one_team_row(db):
    # oncall = team webhook: one row, no per-user recipient, independent of groups
    await seed_incident(db, channels=["oncall"])
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()

    notifications = await rows(db)
    assert created == 1 and len(notifications) == 1
    assert notifications[0].channel == "oncall" and notifications[0].recipient_user_id is None


async def test_refanout_is_idempotent(db):
    user = await seed_user(db, "a@example.com", chat_id="111")
    group = await seed_group(db, "oncall", [user])
    await seed_route(db, group)
    await seed_incident(db)
    await db.commit()

    first = await fan_out_pending(db, now=NOW)
    await db.commit()
    second = await fan_out_pending(db, now=NOW)  # notified_at CAS -> nothing to do
    await db.commit()

    assert first == 1 and second == 0
    assert len(await rows(db)) == 1
