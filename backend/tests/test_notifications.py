from app.api.v1.notifications import MASK


async def test_receiver_secret_encrypted_and_masked(client, db, admin_headers):
    created = await client.post(
        "/api/v1/receivers",
        json={
            "name": "slack-infra",
            "type": "slack",
            "config": {"url": "https://hooks.slack.com/services/SECRET", "channel": "#alerts"},
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["config"]["url"] == MASK
    assert data["config"]["channel"] == "#alerts"

    # Stored value must be Fernet ciphertext, not plaintext.
    from sqlalchemy import select

    from app.core.security import decrypt_secret
    from app.models import Receiver

    receiver = (await db.execute(select(Receiver))).scalar_one()
    assert receiver.config["url"] != "https://hooks.slack.com/services/SECRET"
    assert decrypt_secret(receiver.config["url"]) == "https://hooks.slack.com/services/SECRET"


async def test_receiver_update_keeps_masked_secret(client, db, admin_headers):
    created = await client.post(
        "/api/v1/receivers",
        json={"name": "wh", "type": "webhook", "config": {"url": "https://example.com/hook"}},
        headers=admin_headers,
    )
    receiver_id = created.json()["data"]["id"]

    await client.patch(
        f"/api/v1/receivers/{receiver_id}",
        json={"config": {"url": MASK, "extra": "x"}},
        headers=admin_headers,
    )

    from sqlalchemy import select

    from app.core.security import decrypt_secret
    from app.models import Receiver

    receiver = (await db.execute(select(Receiver))).scalar_one()
    assert decrypt_secret(receiver.config["url"]) == "https://example.com/hook"
    assert receiver.config["extra"] == "x"


async def test_receiver_requires_admin(client, editor_headers):
    res = await client.post(
        "/api/v1/receivers",
        json={"name": "x", "type": "slack", "config": {}},
        headers=editor_headers,
    )
    assert res.status_code == 403


async def test_policy_crud(client, admin_headers):
    receiver = await client.post(
        "/api/v1/receivers",
        json={"name": "r1", "type": "webhook", "config": {}},
        headers=admin_headers,
    )
    receiver_id = receiver.json()["data"]["id"]

    policy = await client.post(
        "/api/v1/notification-policies",
        json={
            "matcher": {"severity": "critical"},
            "receiver_id": receiver_id,
            "group_by": ["alertname"],
            "repeat_interval": "4h",
        },
        headers=admin_headers,
    )
    assert policy.status_code == 201
    policy_id = policy.json()["data"]["id"]

    listed = await client.get("/api/v1/notification-policies", headers=admin_headers)
    assert len(listed.json()["data"]) == 1

    deleted = await client.delete(
        f"/api/v1/notification-policies/{policy_id}", headers=admin_headers
    )
    assert deleted.status_code == 200


async def test_silence_crud(client, editor_headers):
    from app.api.v1.notifications import get_alertmanager_client
    from app.main import app

    class FakeAM:
        async def create_silence(self, silence):
            return "ext-123"

        async def delete_silence(self, silence_id):
            assert silence_id == "ext-123"

    app.dependency_overrides[get_alertmanager_client] = lambda: FakeAM()
    try:
        created = await client.post(
            "/api/v1/silences",
            json={
                "matchers": {"alertname": "HighCPU"},
                "starts_at": "2026-06-10T00:00:00Z",
                "ends_at": "2026-06-11T00:00:00Z",
                "comment": "maintenance window",
            },
            headers=editor_headers,
        )
        assert created.status_code == 201
        silence_id = created.json()["data"]["id"]

        deleted = await client.delete(f"/api/v1/silences/{silence_id}", headers=editor_headers)
        assert deleted.status_code == 200
    finally:
        app.dependency_overrides.pop(get_alertmanager_client, None)


async def test_silence_rejects_inverted_window(client, editor_headers):
    res = await client.post(
        "/api/v1/silences",
        json={
            "matchers": {},
            "starts_at": "2026-06-11T00:00:00Z",
            "ends_at": "2026-06-10T00:00:00Z",
        },
        headers=editor_headers,
    )
    assert res.status_code == 400
