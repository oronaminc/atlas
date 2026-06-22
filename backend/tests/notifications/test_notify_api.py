"""API: manual group send (editor+), settings/routes/recipients (admin), status list."""

from sqlalchemy import select

from app.models.delivery import Notification
from tests.notifications.helpers import seed_group, seed_incident, seed_user


async def seed_basic(db):
    u1 = await seed_user(db, "oncall1@example.com", chat_id="111")
    u2 = await seed_user(db, "oncall2@example.com", chat_id=None)
    group = await seed_group(db, "oncall", [u1, u2])
    incident = await seed_incident(db)
    await db.commit()
    return group, incident


# --- manual send ---


async def test_editor_can_trigger_group_send_and_it_is_audited(
    client, db, editor_headers, admin_headers
):
    group, incident = await seed_basic(db)

    res = await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": str(group.id)},
        headers=editor_headers,
    )
    assert res.status_code == 200
    # telegram for the user with chat_id + email for both members
    assert res.json()["data"]["created"] >= 1

    notifications = list((await db.execute(select(Notification))).scalars())
    assert all(n.status == "pending" for n in notifications)
    assert {n.channel for n in notifications} <= {"telegram", "email"}

    logs = await client.get("/api/v1/audit-logs?resource_type=incident", headers=admin_headers)
    actions = [e["action"] for e in logs.json()["data"]]
    assert "notify" in actions


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


# --- settings (admin) ---


async def test_settings_defaults_and_masked_token(client, admin_headers):
    res = await client.get("/api/v1/notification-settings", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["telegram_rate_per_second"] == 25
    assert data["quota_group_per_hour"] == 30
    assert data["quota_global_per_day"] == 500
    assert data["telegram_bot_token"] is None  # not set yet


async def test_admin_sets_token_stored_encrypted_response_masked(client, db, admin_headers):
    res = await client.patch(
        "/api/v1/notification-settings",
        json={"telegram_bot_token": "123456:SECRET", "quota_group_per_hour": 10},
        headers=admin_headers,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["telegram_bot_token"] == "********"
    assert data["quota_group_per_hour"] == 10

    from app.core.security import decrypt_secret
    from app.models.delivery import NotificationSettings

    row = (await db.execute(select(NotificationSettings))).scalar_one()
    assert row.telegram_bot_token != "123456:SECRET"
    assert decrypt_secret(row.telegram_bot_token) == "123456:SECRET"

    logs = await client.get(
        "/api/v1/audit-logs?resource_type=notification_settings", headers=admin_headers
    )
    assert len(logs.json()["data"]) == 1


async def test_settings_forbidden_for_non_admin(client, editor_headers):
    assert (
        await client.get("/api/v1/notification-settings", headers=editor_headers)
    ).status_code == 403
    assert (
        await client.patch(
            "/api/v1/notification-settings",
            json={"quota_group_per_hour": 1},
            headers=editor_headers,
        )
    ).status_code == 403


# --- recipients (admin, view-only) ---


async def test_recipients_list_admin_only(client, db, admin_headers, viewer_headers):
    group, _ = await seed_basic(db)

    res = await client.get("/api/v1/notification-recipients", headers=admin_headers)
    assert res.status_code == 200
    rows = res.json()["data"]
    by_email = {r["email"]: r for r in rows}
    assert by_email["oncall1@example.com"]["telegram_chat_id"] == "111"
    assert by_email["oncall2@example.com"]["telegram_chat_id"] is None
    assert "oncall" in by_email["oncall1@example.com"]["groups"]

    assert (
        await client.get("/api/v1/notification-recipients", headers=viewer_headers)
    ).status_code == 403


# --- chat_id via existing admin users PATCH ---


async def test_admin_sets_user_chat_id_via_users_patch(client, db, admin_headers):
    user = await seed_user(db, "newbie@example.com")
    await db.commit()

    res = await client.patch(
        f"/api/v1/users/{user.id}",
        json={"telegram_chat_id": "999"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    await db.refresh(user)
    assert user.telegram_chat_id == "999"


# --- delivery status list ---


async def test_notifications_list_by_incident(client, db, editor_headers):
    group, incident = await seed_basic(db)
    await client.post(
        f"/api/v1/incidents/{incident.id}/notify",
        json={"group_id": str(group.id)},
        headers=editor_headers,
    )
    res = await client.get(
        f"/api/v1/notifications?incident_id={incident.id}", headers=editor_headers
    )
    assert res.status_code == 200
    assert len(res.json()["data"]) >= 1
    assert all(n["status"] == "pending" for n in res.json()["data"])
