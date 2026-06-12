async def test_create_user_requires_admin(client, editor_headers):
    res = await client.post(
        "/api/v1/users",
        json={"email": "x@example.com", "username": "xx", "password": "password123"},
        headers=editor_headers,
    )
    assert res.status_code == 403


async def test_user_crud(client, admin_headers):
    created = await client.post(
        "/api/v1/users",
        json={
            "email": "new@example.com",
            "username": "newuser",
            "password": "password123",
            "role": "editor",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/users", headers=admin_headers)
    assert listed.status_code == 200
    emails = [u["email"] for u in listed.json()["data"]]
    assert "new@example.com" in emails

    patched = await client.patch(
        f"/api/v1/users/{user_id}", json={"role": "viewer"}, headers=admin_headers
    )
    assert patched.json()["data"]["role"] == "viewer"

    deleted = await client.delete(f"/api/v1/users/{user_id}", headers=admin_headers)
    assert deleted.status_code == 200


async def test_group_crud_and_members(client, admin, admin_headers, editor):
    created = await client.post(
        "/api/v1/groups",
        json={"name": "platform", "description": "platform team"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    group_id = created.json()["data"]["id"]

    added = await client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": str(editor.id), "role_in_group": "manager"},
        headers=admin_headers,
    )
    assert added.status_code == 201

    members = await client.get(
        f"/api/v1/groups/{group_id}/members", headers=admin_headers
    )
    assert members.json()["data"][0]["username"] == "editor"
    assert members.json()["data"][0]["role_in_group"] == "manager"

    removed = await client.delete(
        f"/api/v1/groups/{group_id}/members/{editor.id}", headers=admin_headers
    )
    assert removed.status_code == 200

    deleted = await client.delete(f"/api/v1/groups/{group_id}", headers=admin_headers)
    assert deleted.status_code == 200


async def test_cursor_pagination(client, admin_headers):
    for i in range(5):
        await client.post(
            "/api/v1/groups", json={"name": f"team-{i}"}, headers=admin_headers
        )
    first = await client.get("/api/v1/groups?limit=2", headers=admin_headers)
    body = first.json()
    assert len(body["data"]) == 2
    assert body["meta"]["has_more"] is True
    cursor = body["meta"]["next_cursor"]
    assert cursor

    second = await client.get(
        f"/api/v1/groups?limit=2&cursor={cursor}", headers=admin_headers
    )
    names_1 = {g["name"] for g in body["data"]}
    names_2 = {g["name"] for g in second.json()["data"]}
    assert names_1.isdisjoint(names_2)
