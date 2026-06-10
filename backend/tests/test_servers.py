async def test_server_crud(client, editor_headers):
    created = await client.post(
        "/api/v1/servers",
        json={
            "name": "web-01",
            "labels": {"job": "node", "env": "prod"},
            "description": "frontend web",
        },
        headers=editor_headers,
    )
    assert created.status_code == 201
    server_id = created.json()["data"]["id"]
    assert created.json()["data"]["labels"]["env"] == "prod"

    dup = await client.post("/api/v1/servers", json={"name": "web-01"}, headers=editor_headers)
    assert dup.status_code == 409

    patched = await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"description": "updated"},
        headers=editor_headers,
    )
    assert patched.json()["data"]["description"] == "updated"

    deleted = await client.delete(f"/api/v1/servers/{server_id}", headers=editor_headers)
    assert deleted.status_code == 200


async def test_viewer_cannot_create_server(client, viewer_headers):
    res = await client.post("/api/v1/servers", json={"name": "nope"}, headers=viewer_headers)
    assert res.status_code == 403


async def test_server_rules_includes_global(client, admin_headers, editor_headers):
    server = await client.post("/api/v1/servers", json={"name": "db-01"}, headers=editor_headers)
    server_id = server.json()["data"]["id"]

    await client.post(
        "/api/v1/rules",
        json={
            "name": "GlobalCPU",
            "scope_type": "global",
            "expr": "avg(cpu_usage) > 0.9",
            "severity": "critical",
        },
        headers=admin_headers,
    )
    await client.post(
        "/api/v1/rules",
        json={
            "name": "DbDiskFull",
            "scope_type": "server",
            "scope_ref_id": server_id,
            "expr": "disk_free_bytes < 1e9",
            "severity": "warning",
        },
        headers=admin_headers,
    )

    res = await client.get(f"/api/v1/servers/{server_id}/rules", headers=editor_headers)
    names = {r["name"] for r in res.json()["data"]}
    assert names == {"GlobalCPU", "DbDiskFull"}
