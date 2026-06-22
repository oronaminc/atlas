from app.api.v1.alerts import get_am_factory
from app.main import app


async def test_active_alerts_proxy(client, viewer_headers):
    class FakeAM:
        async def get_active_alerts(self):
            return [
                {
                    "fingerprint": "abc",
                    "labels": {"alertname": "HighCPU", "severity": "critical"},
                    "annotations": {"summary": "cpu"},
                    "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
                    "startsAt": "2026-06-10T00:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ]

    app.dependency_overrides[get_am_factory] = lambda: lambda org=None: FakeAM()
    try:
        res = await client.get("/api/v1/alerts/active", headers=viewer_headers)
        assert res.status_code == 200
        assert res.json()["data"][0]["labels"]["alertname"] == "HighCPU"
    finally:
        app.dependency_overrides.pop(get_am_factory, None)


async def test_active_alerts_unreachable_returns_502(client, viewer_headers):
    class DownAM:
        async def get_active_alerts(self):
            raise RuntimeError("connection refused")

    app.dependency_overrides[get_am_factory] = lambda: lambda org=None: DownAM()
    try:
        res = await client.get("/api/v1/alerts/active", headers=viewer_headers)
        assert res.status_code == 502
    finally:
        app.dependency_overrides.pop(get_am_factory, None)


async def test_healthz(client):
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "ok"
