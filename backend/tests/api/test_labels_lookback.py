"""DB-managed Mimir label-query lookback: the proxy bounds an omitted start/end
to [now - lookback, now] (default 1h), respects explicit ranges, surfaces the
upstream status instead of a blanket 502, and is admin-tunable at runtime."""

import httpx
import pytest

from app.api.v1.labels import get_query_client
from app.main import app

pytestmark = pytest.mark.asyncio


class FakeQ:
    def __init__(self, raise_422=False):
        self.calls = []
        self.raise_422 = raise_422

    async def label_values(self, name, *, start=None, end=None, match=None):
        self.calls.append({"name": name, "start": start, "end": end})
        if self.raise_422:
            req = httpx.Request("GET", "http://mimir/api/v1/label/cmdb_ci/values")
            resp = httpx.Response(422, text="err-mimir-bucket-index-too-old", request=req)
            raise httpx.HTTPStatusError("422", request=req, response=resp)
        return ["a", "b"]

    async def label_names(self, *, start=None, end=None, match=None):
        self.calls.append({"name": "__names__", "start": start, "end": end})
        return ["cmdb_ci"]

    async def aclose(self):
        pass


def _use(fake):
    app.dependency_overrides[get_query_client] = lambda: fake


async def test_no_param_call_is_bounded_and_not_502(client, admin_headers):
    fake = FakeQ()
    _use(fake)
    try:
        r = await client.get("/api/v1/labels/cmdb_ci/values", headers=admin_headers)
        assert r.status_code == 200, r.text  # was 502 before
        assert r.json()["data"] == ["a", "b"]
        c = fake.calls[0]
        assert c["start"] is not None and c["end"] is not None  # bounded
        assert int(c["end"]) - int(c["start"]) == 3600  # seeded default = 1h
    finally:
        app.dependency_overrides.pop(get_query_client, None)


async def test_seeded_default_is_one_hour(client, db, admin_headers):
    """Explicit: the lazily-seeded row comes out as 1 (not 0/null) on a fresh DB."""
    r = await client.get("/api/v1/mimir-query-config", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["label_query_lookback_hours"] == 1


async def test_explicit_range_respected(client, admin_headers):
    fake = FakeQ()
    _use(fake)
    try:
        await client.get("/api/v1/labels/cmdb_ci/values?start=111&end=222", headers=admin_headers)
        assert fake.calls[0] == {"name": "cmdb_ci", "start": "111", "end": "222"}
    finally:
        app.dependency_overrides.pop(get_query_client, None)


async def test_upstream_422_surfaced_not_502(client, admin_headers):
    fake = FakeQ(raise_422=True)
    _use(fake)
    try:
        r = await client.get("/api/v1/labels/cmdb_ci/values", headers=admin_headers)
        assert r.status_code == 422  # passthrough, not 502
        # errors ride the {data,error,meta} envelope -> upstream body in error.message
        assert "bucket-index-too-old" in r.json()["error"]["message"]
    finally:
        app.dependency_overrides.pop(get_query_client, None)


async def test_admin_can_change_lookback(client, admin_headers):
    p = await client.patch(
        "/api/v1/mimir-query-config",
        json={"label_query_lookback_hours": 6},
        headers=admin_headers,
    )
    assert p.status_code == 200 and p.json()["data"]["label_query_lookback_hours"] == 6
    fake = FakeQ()
    _use(fake)
    try:
        await client.get("/api/v1/labels/cmdb_ci/values", headers=admin_headers)
        assert int(fake.calls[0]["end"]) - int(fake.calls[0]["start"]) == 6 * 3600
    finally:
        app.dependency_overrides.pop(get_query_client, None)


async def test_lookback_bounds_validation(client, admin_headers):
    too_big = await client.patch(
        "/api/v1/mimir-query-config",
        json={"label_query_lookback_hours": 721},
        headers=admin_headers,
    )
    assert too_big.status_code == 422
    too_small = await client.patch(
        "/api/v1/mimir-query-config",
        json={"label_query_lookback_hours": 0},
        headers=admin_headers,
    )
    assert too_small.status_code == 422


async def test_update_requires_admin(client, viewer_headers):
    r = await client.patch(
        "/api/v1/mimir-query-config",
        json={"label_query_lookback_hours": 6},
        headers=viewer_headers,
    )
    assert r.status_code == 403
