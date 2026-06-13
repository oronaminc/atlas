"""RBAC x tenancy matrix: tenant CRUD + user reassignment are HQ-admin only;
tenant-admins manage only their own tenant's users/config."""

from tests.conftest import auth_headers


async def test_tenant_crud_hq_admin_only(client, admin, a_admin, a_editor, viewer):
    body = {"slug": "sub-c", "name": "Subsidiary C", "mimir_orgs": ["org-c"]}
    # tenant-admin: 403; editor/viewer: 403
    for user in (a_admin, a_editor, viewer):
        res = await client.post("/api/v1/tenants", json=body, headers=auth_headers(user))
        assert res.status_code == 403, user.email
    # HQ admin: 201, ingest key shown exactly once
    res = await client.post("/api/v1/tenants", json=body, headers=auth_headers(admin))
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["slug"] == "sub-c" and data["mimir_orgs"] == ["org-c"]
    assert len(data["ingest_key"]) > 20

    # duplicate slug / org -> 409
    res = await client.post("/api/v1/tenants", json=body, headers=auth_headers(admin))
    assert res.status_code == 409


async def test_tenant_list_visibility(client, admin, a_viewer, tenant_a, tenant_b):
    res = await client.get("/api/v1/tenants", headers=auth_headers(admin))
    slugs = [t["slug"] for t in res.json()["data"]]
    assert {"sub-a", "sub-b"} <= set(slugs)
    # tenant user: own tenant only (for label display)
    res = await client.get("/api/v1/tenants", headers=auth_headers(a_viewer))
    assert [t["slug"] for t in res.json()["data"]] == ["sub-a"]


async def test_user_tenant_reassignment_hq_only(client, db, admin, a_admin, viewer, tenant_b):
    # HQ admin moves a user to tenant B
    res = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"tenant_id": str(tenant_b.id)},
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["tenant_id"] == str(tenant_b.id)

    # ...and promotes them to HQ with explicit null
    res = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"tenant_id": None},
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["tenant_id"] is None

    # tenant-admin cannot reassign anyone (even own-tenant users)
    res = await client.patch(
        f"/api/v1/users/{a_admin.id}",
        json={"tenant_id": None},
        headers=auth_headers(a_admin),
    )
    assert res.status_code == 403

    # reassignment is audited
    res = await client.get("/api/v1/audit-logs?resource_type=user", headers=auth_headers(admin))
    assert any(e["action"] == "update" for e in res.json()["data"])


async def test_tenant_admin_sees_only_own_users(client, admin, a_admin, b_viewer, tenant_a):
    res = await client.get("/api/v1/users", headers=auth_headers(a_admin))
    emails = [u["email"] for u in res.json()["data"]]
    assert "viewer-b@example.com" not in emails
    assert all("-a@example.com" in e or e.startswith("member-a") for e in emails)

    # direct fetch of another tenant's user -> 404
    res = await client.get(f"/api/v1/users/{b_viewer.id}", headers=auth_headers(a_admin))
    assert res.status_code == 404

    # tenant-admin creating a user is forced into their own tenant
    res = await client.post(
        "/api/v1/users",
        json={
            "email": "new-a@example.com",
            "username": "new-a",
            "password": "password123",
            "role": "viewer",
        },
        headers=auth_headers(a_admin),
    )
    assert res.status_code == 201
    assert res.json()["data"]["tenant_id"] == str(tenant_a.id)


async def test_per_tenant_notification_settings_api(client, admin, a_admin, tenant_a, tenant_b):
    # tenant-admin reads/writes their own row implicitly
    res = await client.patch(
        "/api/v1/notification-settings",
        json={"quota_group_per_hour": 77},
        headers=auth_headers(a_admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["quota_group_per_hour"] == 77

    # HQ reads B's row via ?tenant= and sees defaults, not A's 77
    res = await client.get(
        "/api/v1/notification-settings?tenant=sub-b", headers=auth_headers(admin)
    )
    assert res.json()["data"]["quota_group_per_hour"] == 30

    # HQ reads A's row and sees 77
    res = await client.get(
        "/api/v1/notification-settings?tenant=sub-a", headers=auth_headers(admin)
    )
    assert res.json()["data"]["quota_group_per_hour"] == 77
