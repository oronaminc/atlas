"""Feature B search: per-type correctness, tenancy isolation (service A
search returns ZERO B rows; HQ sees all), window enforcement. PG GIN/EXPLAIN
lives in tests/pg/test_search_scale.py."""

from datetime import UTC, datetime, timedelta

from app.models.alerting import AlertEvent, Incident, IncidentStatus
from tests.conftest import auth_headers

NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


async def _incident(db, tenant_id, *, title, group_key, host, name="HighCPU", when=None):
    when = when or datetime.now(UTC)
    inc = Incident(
        tenant_id=tenant_id,
        title=title,
        status=IncidentStatus.open,
        severity="critical",
        group_key=group_key,
        first_seen=when,
        last_seen=when,
        alert_count=1,
        cmdb_service_l2_code="L2TEST",
    )
    db.add(inc)
    await db.flush()
    db.add(
        AlertEvent(
            tenant_id=tenant_id,
            fingerprint=f"fp-{title}",
            source="am",
            name=name,
            severity="critical",
            status="firing",
            labels={"host": host, "dc": "seoul"},
            annotations={},
            starts_at=when,
            received_at=when,
            incident_id=inc.id,
            cmdb_service_l2_code="L2TEST",
        )
    )
    await db.flush()
    return inc


async def test_host_search(client, db, tenant_a, a_viewer):
    await _incident(db, tenant_a.id, title="cpu on web-01", group_key="host=web-01", host="web-01")
    await _incident(db, tenant_a.id, title="mem on db-01", group_key="host=db-01", host="db-01")
    await db.commit()
    res = await client.get("/api/v1/search?q=web&type=host", headers=auth_headers(a_viewer))
    data = res.json()["data"]
    assert data["type"] == "host"
    assert [r["host"] for r in data["results"]] == ["host=web-01"]


async def test_label_search_exact_kv(client, db, tenant_a, a_viewer):
    await _incident(db, tenant_a.id, title="a", group_key="host=web-01", host="web-01")
    await _incident(db, tenant_a.id, title="b", group_key="host=db-01", host="db-01")
    await db.commit()
    res = await client.get("/api/v1/search?q=host=db-01&type=label", headers=auth_headers(a_viewer))
    data = res.json()["data"]
    assert data["type"] == "label"
    assert len(data["results"]) == 1
    assert data["results"][0]["labels"]["host"] == "db-01"


async def test_label_search_requires_kv(client, db, tenant_a, a_viewer):
    res = await client.get("/api/v1/search?q=justtext&type=label", headers=auth_headers(a_viewer))
    assert res.json()["data"]["results"] == []


async def test_text_search_incident_title(client, db, tenant_a, a_viewer):
    await _incident(
        db, tenant_a.id, title="DiskFull on db-01", group_key="host=db-01", host="db-01"
    )
    await _incident(
        db, tenant_a.id, title="HighCPU on web-01", group_key="host=web-01", host="web-01"
    )
    await db.commit()
    res = await client.get("/api/v1/search?q=diskfull&type=text", headers=auth_headers(a_viewer))
    titles = [r["title"] for r in res.json()["data"]["results"]]
    assert titles == ["DiskFull on db-01"]


async def test_label_window_excludes_old_events(client, db, tenant_a, a_viewer):
    old = datetime.now(UTC) - timedelta(days=10)
    await _incident(db, tenant_a.id, title="old", group_key="host=old-01", host="old-01", when=old)
    await db.commit()
    # default 7d window -> the 10d-old event is excluded
    res = await client.get(
        "/api/v1/search?q=host=old-01&type=label", headers=auth_headers(a_viewer)
    )
    assert res.json()["data"]["results"] == []
    # widen to 30d -> found
    res = await client.get(
        "/api/v1/search?q=host=old-01&type=label&since=30", headers=auth_headers(a_viewer)
    )
    assert len(res.json()["data"]["results"]) == 1


async def test_window_capped_at_30(client, a_viewer):
    res = await client.get(
        "/api/v1/search?q=x&type=label&since=999", headers=auth_headers(a_viewer)
    )
    assert res.status_code == 422  # ge/le validation


# --- tenancy isolation: the core requirement ---


async def test_host_search_tenant_isolated(client, db, tenant_a, tenant_b, a_viewer, b_viewer):
    await _incident(db, tenant_a.id, title="a-cpu", group_key="host=shared-01", host="shared-01")
    await _incident(db, tenant_b.id, title="b-cpu", group_key="host=shared-01", host="shared-01")
    await db.commit()
    # A and B both have host=shared-01; each sees only their own incident count
    a = await client.get("/api/v1/search?q=shared&type=host", headers=auth_headers(a_viewer))
    assert a.json()["data"]["results"] == [
        {
            "host": "host=shared-01",
            "incidents": 1,
            "last_seen": a.json()["data"]["results"][0]["last_seen"],
        }
    ]
    b = await client.get("/api/v1/search?q=shared&type=host", headers=auth_headers(b_viewer))
    assert b.json()["data"]["results"][0]["incidents"] == 1  # not 2


async def test_label_search_tenant_isolated(client, db, tenant_a, tenant_b, a_viewer):
    await _incident(db, tenant_a.id, title="a", group_key="host=x", host="x")
    await _incident(db, tenant_b.id, title="b", group_key="host=x", host="x")
    await db.commit()
    res = await client.get("/api/v1/search?q=host=x&type=label", headers=auth_headers(a_viewer))
    rows = res.json()["data"]["results"]
    assert len(rows) == 1  # only A's event, never B's


async def test_text_search_tenant_isolated(client, db, tenant_a, tenant_b, a_viewer, b_viewer):
    await _incident(db, tenant_a.id, title="OutageX on a", group_key="host=a", host="a")
    await _incident(db, tenant_b.id, title="OutageX on b", group_key="host=b", host="b")
    await db.commit()
    res = await client.get("/api/v1/search?q=OutageX&type=text", headers=auth_headers(a_viewer))
    titles = [r["title"] for r in res.json()["data"]["results"]]
    assert titles == ["OutageX on a"]


async def test_hq_sees_all_services(client, db, tenant_a, tenant_b, admin):
    await _incident(db, tenant_a.id, title="OutageX on a", group_key="host=a", host="a")
    await _incident(db, tenant_b.id, title="OutageX on b", group_key="host=b", host="b")
    await db.commit()
    res = await client.get("/api/v1/search?q=OutageX&type=text", headers=auth_headers(admin))
    titles = sorted(r["title"] for r in res.json()["data"]["results"])
    assert titles == ["OutageX on a", "OutageX on b"]
