"""Silence API: read from cache (all), gated write to Alertmanager with
server-built matchers (service->cmdb_service_l2_code, server->cmdb_ci)."""

import pytest

from app.api.v1.notifications import get_alertmanager_client
from app.main import app

pytestmark = pytest.mark.asyncio


class FakeAM:
    def __init__(self):
        self.store: list[dict] = []
        self.created: list[dict] = []
        self.deleted: list[str] = []

    async def create_silence(self, payload):
        sid = f"sil-{len(self.created)}"
        self.created.append(payload)
        self.store.append(
            {
                "id": sid,
                "status": {"state": "active"},
                "matchers": payload["matchers"],
                "startsAt": payload["startsAt"],
                "endsAt": payload["endsAt"],
                "comment": payload["comment"],
                "createdBy": payload["createdBy"],
            }
        )
        return sid

    async def delete_silence(self, sid):
        self.deleted.append(sid)
        self.store = [s for s in self.store if s["id"] != sid]

    async def get_silences(self):
        return self.store

    async def aclose(self):
        pass


def _body(kind, value):
    return {
        "target_kind": kind,
        "target_value": value,
        "starts_at": "2026-06-22T10:00:00+00:00",
        "ends_at": "2026-06-22T14:00:00+00:00",
        "comment": "maintenance",
    }


async def _with_am(fn):
    fake = FakeAM()
    app.dependency_overrides[get_alertmanager_client] = lambda: fake
    try:
        return await fn(fake)
    finally:
        app.dependency_overrides.pop(get_alertmanager_client, None)


async def test_create_service_silence_builds_matcher_and_caches(
    client, editor_headers, viewer_headers
):
    async def run(fake):
        r = await client.post(
            "/api/v1/silences", json=_body("service", "PAY-L2"), headers=editor_headers
        )
        assert r.status_code == 201
        assert r.json()["data"]["matcher"]["name"] == "cmdb_service_l2_code"
        assert fake.created[0]["matchers"][0]["value"] == "PAY-L2"
        # cache refreshed -> visible to any user (viewer)
        rows = (await client.get("/api/v1/silences", headers=viewer_headers)).json()["data"]
        assert len(rows) == 1 and rows[0]["matchers"][0]["name"] == "cmdb_service_l2_code"

    await _with_am(run)


async def test_create_server_silence_uses_cmdb_ci(client, editor_headers):
    async def run(fake):
        r = await client.post(
            "/api/v1/silences", json=_body("server", "CI-7"), headers=editor_headers
        )
        assert r.status_code == 201
        assert fake.created[0]["matchers"][0]["name"] == "cmdb_ci"

    await _with_am(run)


async def test_delete_silence_calls_am_and_refreshes(client, editor_headers):
    async def run(fake):
        sid = (
            await client.post(
                "/api/v1/silences", json=_body("service", "X"), headers=editor_headers
            )
        ).json()["data"]["silence_id"]
        r = await client.delete(f"/api/v1/silences/{sid}", headers=editor_headers)
        assert r.status_code == 200 and sid in fake.deleted
        rows = (await client.get("/api/v1/silences", headers=editor_headers)).json()["data"]
        assert rows == []

    await _with_am(run)


async def test_bad_window_400(client, editor_headers):
    async def run(_fake):
        bad = _body("service", "X")
        bad["ends_at"] = bad["starts_at"]
        r = await client.post("/api/v1/silences", json=bad, headers=editor_headers)
        assert r.status_code == 400

    await _with_am(run)


async def test_viewer_can_read_not_write(client, viewer_headers):
    async def run(_fake):
        assert (await client.get("/api/v1/silences", headers=viewer_headers)).status_code == 200
        post = await client.post(
            "/api/v1/silences", json=_body("service", "X"), headers=viewer_headers
        )
        assert post.status_code == 403
        assert (
            await client.delete("/api/v1/silences/sil-0", headers=viewer_headers)
        ).status_code == 403

    await _with_am(run)
