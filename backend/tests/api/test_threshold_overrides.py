"""Threshold catalog + override API: catalog upsert, override CRUD + 409 dup,
validation, viewer RBAC, rule-catalog union of seen alertnames, tenancy."""

from tests.conftest import auth_headers


async def test_rule_catalog_upsert_and_union(client, admin, db):
    from tests.notifications.helpers import seed_incident_with_events

    await seed_incident_with_events(db, [("CS_1", "HostOutOfMemory")])
    await db.commit()
    # uncataloged alertname appears with null metadata
    rows = (await client.get("/api/v1/rule-catalog", headers=auth_headers(admin))).json()["data"]
    assert any(r["alertname"] == "HostOutOfMemory" and r["value_query"] is None for r in rows)
    # configure it
    r = await client.patch(
        "/api/v1/rule-catalog/HostOutOfMemory",
        json={"comparator": ">", "unit": "%", "value_query": 'm{cmdb_ci="{{cmdb_ci}}"}'},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    rows = (await client.get("/api/v1/rule-catalog", headers=auth_headers(admin))).json()["data"]
    cfg = next(x for x in rows if x["alertname"] == "HostOutOfMemory")
    assert cfg["comparator"] == ">" and cfg["value_query"].startswith("m{")


async def test_override_crud_and_dup(client, admin):
    bad = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "tier": "server", "value": 90},
        headers=auth_headers(admin),
    )
    assert bad.status_code == 422  # server tier requires cmdb_ci

    ok = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "tier": "server", "target_cmdb_ci": "CS_1", "value": 90},
        headers=auth_headers(admin),
    )
    assert ok.status_code == 201
    oid = ok.json()["data"]["id"]

    dup = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "tier": "server", "target_cmdb_ci": "CS_1", "value": 70},
        headers=auth_headers(admin),
    )
    assert dup.status_code == 409

    upd = await client.patch(
        f"/api/v1/threshold-overrides/{oid}", json={"value": 75}, headers=auth_headers(admin)
    )
    assert upd.json()["data"]["value"] == 75

    lst = (await client.get("/api/v1/threshold-overrides", headers=auth_headers(admin))).json()[
        "data"
    ]
    assert len(lst) == 1
    assert (
        await client.delete(f"/api/v1/threshold-overrides/{oid}", headers=auth_headers(admin))
    ).status_code == 200


async def test_viewer_cannot_create_override(client, viewer):
    r = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "tier": "server", "target_cmdb_ci": "CS_1", "value": 90},
        headers=auth_headers(viewer),
    )
    assert r.status_code == 403
