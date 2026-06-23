"""API: manual group send (editor+), recipients list (admin), delivery status."""

import pytest
from sqlalchemy import select

from app.models.delivery import Notification
from tests.notifications.helpers import seed_group, seed_group_channel, seed_incident, seed_user

pytestmark = pytest.mark.asyncio


async def seed_basic(db):
    group = await seed_group(db, "oncall", [])
    await seed_group_channel(db, group, "telegram", bot_token="b", chat_id="111")
    await seed_group_channel(db, group, "email", email="ops@x.io")
    incident = await seed_incident(db)
    await db.commit()
    return group, incident


async def test_editor_can_trigger_group_send_and_it_is_audited(
    client, db, editor_headers, admin_headers
):
    group, incident = await seed_basic(db)
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": str(group.id)},
        headers=editor_headers,
    )
    assert res.status_code == 200 and res.json()["data"]["created"] == 2  # telegram + email
    notifications = list((await db.execute(select(Notification))).scalars())
    assert {n.channel for n in notifications} == {"telegram", "email"}
    logs = await client.get("/api/v1/audit-logs?resource_type=incident", headers=admin_headers)
    assert "notify" in [e["action"] for e in logs.json()["data"]]


async def test_viewer_cannot_trigger_group_send(client, db, viewer_headers):
    group, incident = await seed_basic(db)
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": str(group.id)},
        headers=viewer_headers,
    )
    assert res.status_code == 403


async def test_notify_unknown_group_404(client, db, editor_headers):
    _, incident = await seed_basic(db)
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": "00000000-0000-0000-0000-000000000000"},
        headers=editor_headers,
    )
    assert res.status_code == 404


async def test_recipients_list_admin_only(client, db, admin_headers, viewer_headers):
    u = await seed_user(db, "oncall1@example.com", chat_id="111")
    await seed_group(db, "oncall", [u])
    await db.commit()
    res = await client.get("/api/v1/notification-recipients", headers=admin_headers)
    assert res.status_code == 200
    by_email = {r["email"]: r for r in res.json()["data"]}
    assert by_email["oncall1@example.com"]["telegram_chat_id"] == "111"
    assert (
        await client.get("/api/v1/notification-recipients", headers=viewer_headers)
    ).status_code == 403


async def test_notifications_list_by_incident_and_channel(client, db, editor_headers):
    group, incident = await seed_basic(db)
    await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": str(group.id)},
        headers=editor_headers,
    )
    res = await client.get(
        f"/api/v1/notifications?incident_id={incident.id}", headers=editor_headers
    )
    assert res.status_code == 200 and len(res.json()["data"]) == 2
    only_tg = await client.get(
        f"/api/v1/notifications?incident_id={incident.id}&channel=telegram", headers=editor_headers
    )
    assert len(only_tg.json()["data"]) == 1
