"""IMP stage 7: new label-based API surface — alerts browse + group_by, incident
promote/attach/detach + channel toggles, grouping-rules / notification-defaults /
group-service-codes admin CRUD."""

from datetime import UTC, datetime

import pytest_asyncio

from app.models.alerting import AlertEvent

NOW = datetime(2026, 6, 20, 0, 0, 0, tzinfo=UTC)
L2 = "L2TEST"  # matches the editor/viewer fixtures' mapping


def _alert(fp, *, l2=L2, sev="critical", incident_id=None, **labels):
    base = {
        "cmdb_ci": f"CS-{fp}",
        "cmdb_hostname": f"host-{fp}",
        "cmdb_zone": "Z1",
        "client_address": "10.0.0.1",
        "cmdb_service_l1_code": "L1",
        "cmdb_service_l2_code": l2,
    }
    base.update(labels)
    return AlertEvent(
        fingerprint=fp,
        source="alertmanager",
        name="HostHighCpuLoad",
        severity=sev,
        status="firing",
        labels={"cmdb_service_l2_code": l2},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        incident_id=incident_id,
        **base,
    )


@pytest_asyncio.fixture
async def alerts(db):
    rows = [
        _alert("a1", cmdb_zone="Z1"),
        _alert("a2", cmdb_zone="Z2"),
        _alert("a3", client_address="10.0.0.2"),
    ]
    db.add_all(rows)
    await db.commit()
    return rows


# ---------- alerts browse ----------
async def test_list_all_alerts(client, alerts, admin_headers):
    res = await client.get("/api/v1/alerts", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json()["data"]) == 3


async def test_filter_by_zone(client, alerts, admin_headers):
    res = await client.get("/api/v1/alerts?cmdb_zone=Z2", headers=admin_headers)
    data = res.json()["data"]
    assert len(data) == 1 and data[0]["cmdb_zone"] == "Z2"


async def test_group_by_client_address(client, alerts, admin_headers):
    res = await client.get("/api/v1/alerts?group_by=client_address", headers=admin_headers)
    groups = {g["value"]: g["count"] for g in res.json()["data"]}
    assert groups == {"10.0.0.1": 2, "10.0.0.2": 1}


async def test_group_by_invalid_422(client, admin_headers):
    res = await client.get("/api/v1/alerts?group_by=cmdb_ci", headers=admin_headers)
    assert res.status_code == 422


async def test_alert_detail(client, alerts, admin_headers):
    res = await client.get(f"/api/v1/alerts/{alerts[0].id}", headers=admin_headers)
    assert res.status_code == 200 and res.json()["data"]["cmdb_ci"] == "CS-a1"


# ---------- incident manual ops ----------
async def test_promote_then_attach_then_detach(client, db, alerts, editor_headers):
    a1, a2 = alerts[0], alerts[1]
    # promote a1 -> new manual incident
    res = await client.post(
        "/api/v1/incidents", json={"alert_id": str(a1.id)}, headers=editor_headers
    )
    assert res.status_code == 201
    inc = res.json()["data"]
    assert inc["origin"] == "manual" and inc["alert_count"] == 1

    # attach a2
    res = await client.post(
        f"/api/v1/incidents/{inc['id']}/alerts",
        json={"alert_id": str(a2.id)},
        headers=editor_headers,
    )
    assert res.status_code == 200 and res.json()["data"]["alert_count"] == 2

    # re-attach a2 elsewhere -> 409
    res2 = await client.post(
        "/api/v1/incidents", json={"alert_id": str(a2.id)}, headers=editor_headers
    )
    assert res2.status_code == 409

    # detach a2
    res = await client.delete(
        f"/api/v1/incidents/{inc['id']}/alerts/{a2.id}", headers=editor_headers
    )
    assert res.status_code == 200


async def test_detach_last_alert_forbidden_then_delete(client, db, alerts, editor_headers):
    # A4: an incident can never have 0 alerts. Detaching the last alert is 409;
    # to dissolve, DELETE the incident (frees its alert).
    res = await client.post(
        "/api/v1/incidents", json={"alert_id": str(alerts[0].id)}, headers=editor_headers
    )
    inc_id = res.json()["data"]["id"]
    detach = await client.delete(
        f"/api/v1/incidents/{inc_id}/alerts/{alerts[0].id}", headers=editor_headers
    )
    assert detach.status_code == 409  # last alert
    deleted = await client.delete(f"/api/v1/incidents/{inc_id}", headers=editor_headers)
    assert deleted.status_code == 200 and deleted.json()["data"]["freed_alerts"] == 1
    assert (
        await client.get(f"/api/v1/incidents/{inc_id}", headers=editor_headers)
    ).status_code == 404
    # the freed alert survives, unattached
    alert = (await client.get(f"/api/v1/alerts/{alerts[0].id}", headers=editor_headers)).json()[
        "data"
    ]
    assert alert["incident_id"] is None


async def test_channel_toggles_patch(client, alerts, editor_headers):
    res = await client.post(
        "/api/v1/incidents", json={"alert_id": str(alerts[0].id)}, headers=editor_headers
    )
    inc_id = res.json()["data"]["id"]
    res = await client.patch(
        f"/api/v1/incidents/{inc_id}",
        json={"notify_email": False, "notify_oncall": True},
        headers=editor_headers,
    )
    data = res.json()["data"]
    assert data["notify_email"] is False and data["notify_oncall"] is True


async def test_promote_requires_editor(client, alerts, viewer_headers):
    res = await client.post(
        "/api/v1/incidents", json={"alert_id": str(alerts[0].id)}, headers=viewer_headers
    )
    assert res.status_code == 403


# ---------- admin CRUD ----------
async def test_grouping_rules_get_and_patch(client, db, admin_headers):
    res = await client.get("/api/v1/grouping-rules", headers=admin_headers)
    rules = res.json()["data"]
    assert len(rules) == 1 and rules[0]["label_keys"] == ["cmdb_service_l2_code"]
    rid = rules[0]["id"]
    res = await client.patch(
        f"/api/v1/grouping-rules/{rid}", json={"min_group_size": 3}, headers=admin_headers
    )
    assert res.json()["data"]["min_group_size"] == 3


async def test_grouping_rule_patch_requires_admin(client, db, editor_headers):
    g = await client.get("/api/v1/grouping-rules", headers=editor_headers)
    rid = g.json()["data"][0]["id"]
    res = await client.patch(
        f"/api/v1/grouping-rules/{rid}", json={"min_group_size": 3}, headers=editor_headers
    )
    assert res.status_code == 403


async def test_notification_defaults_get_patch(client, admin_headers):
    res = await client.get("/api/v1/notification-defaults", headers=admin_headers)
    assert res.json()["data"]["default_email"] is True
    res = await client.patch(
        "/api/v1/notification-defaults", json={"default_oncall": True}, headers=admin_headers
    )
    assert res.json()["data"]["default_oncall"] is True


async def test_group_service_codes_set_and_list(client, db, admin, admin_headers):
    from app.models.group import Group

    g = Group(name="svc-team")
    db.add(g)
    await db.commit()
    res = await client.put(
        f"/api/v1/groups/{g.id}/service-codes",
        json={"codes": ["sub-a", "sub-b", "sub-a"]},  # dup ignored
        headers=admin_headers,
    )
    assert sorted(res.json()["data"]["codes"]) == ["sub-a", "sub-b"]
    res = await client.get(f"/api/v1/groups/{g.id}/service-codes", headers=admin_headers)
    assert sorted(res.json()["data"]["codes"]) == ["sub-a", "sub-b"]
    # replace (idempotent): drop sub-b, keep sub-a, add sub-c
    res = await client.put(
        f"/api/v1/groups/{g.id}/service-codes",
        json={"codes": ["sub-a", "sub-c"]},
        headers=admin_headers,
    )
    assert sorted(res.json()["data"]["codes"]) == ["sub-a", "sub-c"]
