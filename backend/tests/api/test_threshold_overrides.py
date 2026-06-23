"""Threshold override API: label-based target CRUD + 409 dup, validation,
viewer RBAC. (rule-catalog/value_query removed — no PromQL.)"""

from tests.conftest import auth_headers


async def test_override_crud_and_dup(client, admin):
    bad = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "value": 90},  # no target -> invalid
        headers=auth_headers(admin),
    )
    assert bad.status_code == 422

    ok = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "target_cmdb_ci": "CS_1", "value": 90},
        headers=auth_headers(admin),
    )
    assert ok.status_code == 201
    oid = ok.json()["data"]["id"]

    dup = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "target_cmdb_ci": "CS_1", "value": 70},
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


async def test_per_service_override_create(client, admin):
    r = await client.post(
        "/api/v1/threshold-overrides",
        json={
            "alertname": "A",
            "target_label_key": "cmdb_service_l2_code",
            "target_label_value": "PAY-L2",
            "value": 90,
        },
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    assert r.json()["data"]["target_label_value"] == "PAY-L2"


async def test_viewer_cannot_create_override(client, viewer):
    r = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "A", "target_cmdb_ci": "CS_1", "value": 90},
        headers=auth_headers(viewer),
    )
    assert r.status_code == 403
