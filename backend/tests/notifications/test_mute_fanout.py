"""Fan-out respects mutes: a fully-muted incident creates ZERO notifications
(and records a timeline event); a non-muted sibling still notifies."""

from sqlalchemy import select

from app.models.alerting import IncidentEvent
from app.models.delivery import Notification, NotificationMute
from app.notifications.fanout import fan_out_pending
from tests.notifications.helpers import (
    NOW,
    seed_group,
    seed_incident_with_events,
    seed_route,
    seed_user,
)


async def _setup_route(db):
    u1 = await seed_user(db, "a@example.com", chat_id="111")
    u2 = await seed_user(db, "b@example.com", chat_id="222")
    group = await seed_group(db, "oncall", [u1, u2])
    await seed_route(db, group, min_severity="warning", channels=["telegram"])


async def test_muted_incident_creates_no_notifications(db):
    await _setup_route(db)
    await seed_incident_with_events(db, [("X", "HostOutOfMemory")])
    db.add(NotificationMute(target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory"))
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()

    assert created == 0
    assert (await db.execute(select(Notification))).scalars().first() is None
    kinds = [e.kind for e in (await db.execute(select(IncidentEvent))).scalars()]
    assert "notification_muted" in kinds


async def test_non_muted_incident_still_notifies(db):
    await _setup_route(db)
    await seed_incident_with_events(db, [("X", "HostHighCPU")])  # different alertname
    db.add(NotificationMute(target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory"))
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()

    assert created == 2  # both telegram members


async def test_partial_mute_still_notifies(db):
    await _setup_route(db)
    # incident carries one muted + one live alert -> must still notify
    await seed_incident_with_events(db, [("X", "HostOutOfMemory"), ("X", "HostHighCPU")])
    db.add(NotificationMute(target_type="server", target_cmdb_ci="X", alertname="HostOutOfMemory"))
    await db.commit()

    created = await fan_out_pending(db, now=NOW)
    await db.commit()
    assert created == 2
