"""Server-group + bulk cmdb_ci upload API: create, dedupe, malformed-reject,
1:1 reassign across groups, rule catalog, mute CRUD + wildcard validation."""

from tests.conftest import auth_headers


async def _group(client, admin, name):
    r = await client.post("/api/v1/server-groups", json={"name": name}, headers=auth_headers(admin))
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def test_bulk_upload_dedupe_and_reject(client, admin):
    gid = await _group(client, admin, "db-tier")
    r = await client.post(
        f"/api/v1/server-groups/{gid}/members/bulk",
        json={"cmdb_cis": ["CS_1", "CS_1", "CS_2", "bad ci!", "  ", "CS_3"]},
        headers=auth_headers(admin),
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["added"] == 3  # CS_1, CS_2, CS_3
    assert "bad ci!" in d["rejected"] and "" in [x.strip() for x in d["rejected"]]
    members = (
        await client.get(f"/api/v1/server-groups/{gid}/members", headers=auth_headers(admin))
    ).json()["data"]
    assert {m["cmdb_ci"] for m in members} == {"CS_1", "CS_2", "CS_3"}


async def test_one_to_one_reassign_moves_server(client, admin):
    g1 = await _group(client, admin, "g1")
    g2 = await _group(client, admin, "g2")
    await client.post(
        f"/api/v1/server-groups/{g1}/members/bulk",
        json={"cmdb_cis": ["CS_X"]},
        headers=auth_headers(admin),
    )
    # re-upload same cmdb_ci into g2 -> reassigned (1:1), removed from g1
    r = await client.post(
        f"/api/v1/server-groups/{g2}/members/bulk",
        json={"cmdb_cis": ["CS_X"]},
        headers=auth_headers(admin),
    )
    assert r.json()["data"]["reassigned"] == 1
    g1m = (
        await client.get(f"/api/v1/server-groups/{g1}/members", headers=auth_headers(admin))
    ).json()["data"]
    g2m = (
        await client.get(f"/api/v1/server-groups/{g2}/members", headers=auth_headers(admin))
    ).json()["data"]
    assert g1m == []
    assert {m["cmdb_ci"] for m in g2m} == {"CS_X"}


async def test_bulk_large_list(client, admin):
    gid = await _group(client, admin, "big")
    cis = [f"CS_{i}" for i in range(500)]
    r = await client.post(
        f"/api/v1/server-groups/{gid}/members/bulk",
        json={"cmdb_cis": cis},
        headers=auth_headers(admin),
    )
    assert r.json()["data"]["added"] == 500


async def test_viewer_cannot_create_group(client, viewer):
    r = await client.post("/api/v1/server-groups", json={"name": "x"}, headers=auth_headers(viewer))
    assert r.status_code == 403


async def test_mute_crud_and_wildcard_validation(client, admin):
    # server mute requires cmdb_ci
    bad = await client.post(
        "/api/v1/mutes",
        json={"target_type": "server", "alertname": "A"},
        headers=auth_headers(admin),
    )
    assert bad.status_code == 422
    # 'all' without alertname rejected (would mute everything)
    bad2 = await client.post(
        "/api/v1/mutes", json={"target_type": "all"}, headers=auth_headers(admin)
    )
    assert bad2.status_code == 422
    # valid server mute
    ok = await client.post(
        "/api/v1/mutes",
        json={"target_type": "server", "target_cmdb_ci": "CS_1", "alertname": "HostOutOfMemory"},
        headers=auth_headers(admin),
    )
    assert ok.status_code == 201
    mid = ok.json()["data"]["id"]
    # duplicate -> 409
    dup = await client.post(
        "/api/v1/mutes",
        json={"target_type": "server", "target_cmdb_ci": "CS_1", "alertname": "HostOutOfMemory"},
        headers=auth_headers(admin),
    )
    assert dup.status_code == 409
    lst = (await client.get("/api/v1/mutes", headers=auth_headers(admin))).json()["data"]
    assert len(lst) == 1
    assert (
        await client.delete(f"/api/v1/mutes/{mid}", headers=auth_headers(admin))
    ).status_code == 200


async def test_rule_catalog_from_seen_alertnames(client, admin, db):
    from tests.notifications.helpers import seed_incident_with_events

    await seed_incident_with_events(db, [("CS_1", "HostOutOfMemory"), ("CS_2", "HostHighCPU")])
    await db.commit()
    r = await client.get("/api/v1/mutes/rule-catalog", headers=auth_headers(admin))
    assert r.status_code == 200
    assert set(r.json()["data"]["alertnames"]) >= {"HostOutOfMemory", "HostHighCPU"}
