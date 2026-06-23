"""Read endpoints over the Mimir cache + label proxy."""

import pytest

from app.main import app
from app.models.base import utcnow
from app.models.mimir import MimirRule, MimirSilence

pytestmark = pytest.mark.asyncio


async def _seed(db):
    db.add(
        MimirRule(
            alertname="HighCPU",
            group_name="cpu",
            namespace="ns1",
            expr="cpu > 80",
            for_seconds=300,
            severity="warning",
            labels={"severity": "warning"},
            annotations={},
            health="err",
            state="inactive",
            last_error="parse error",
            value=83.0,
            base_threshold=80.0,
            comparator=">",
            synced_at=utcnow(),
        )
    )
    db.add(
        MimirSilence(
            silence_id="sil-1",
            matchers=[{"name": "cmdb_ci", "value": "CI-1"}],
            comment="maint",
            state="active",
            synced_at=utcnow(),
        )
    )
    await db.commit()


async def test_pulled_rules_from_cache(db, client, admin_headers):
    await _seed(db)
    r = await client.get("/api/v1/rules/pulled", headers=admin_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["alertname"] == "HighCPU"
    assert rows[0]["base_threshold"] == 80.0
    assert rows[0]["last_error"] == "parse error"  # eval error surfaced


async def test_silences_from_cache(db, client, admin_headers):
    await _seed(db)
    r = await client.get("/api/v1/silences", headers=admin_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows[0]["silence_id"] == "sil-1"
    assert rows[0]["state"] == "active"


async def test_label_names_and_values_proxy(client, admin_headers):
    from app.api.v1.labels import get_query_client

    class FakeQ:
        async def label_names(self, **kw):
            return ["cmdb_hostname", "cmdb_zone", "client_address"]

        async def label_values(self, name, **kw):
            return [f"{name}-a", f"{name}-b"]

        async def aclose(self):
            pass

    app.dependency_overrides[get_query_client] = lambda: FakeQ()
    try:
        r = await client.get("/api/v1/labels", headers=admin_headers)
        assert r.status_code == 200
        assert "cmdb_hostname" in r.json()["data"]
        r2 = await client.get("/api/v1/labels/cmdb_zone/values", headers=admin_headers)
        assert r2.json()["data"] == ["cmdb_zone-a", "cmdb_zone-b"]
    finally:
        app.dependency_overrides.pop(get_query_client, None)
