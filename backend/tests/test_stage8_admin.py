"""Stage 8: group labels (metadata), admin password reset, numbered pagination."""

import pytest

from app.core.security import verify_password
from app.models import Group
from app.models.user import GlobalRole

pytestmark = pytest.mark.asyncio


async def test_group_labels_crud(client, db, admin, admin_headers):
    g = Group(name="svc-team")
    db.add(g)
    await db.commit()
    r = await client.patch(
        f"/api/v1/groups/{g.id}",
        json={"labels": ["cmdb_zone", "cmdb_hostname"]},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["data"]["labels"] == ["cmdb_zone", "cmdb_hostname"]
    got = (await client.get(f"/api/v1/groups/{g.id}", headers=admin_headers)).json()["data"]
    assert got["labels"] == ["cmdb_zone", "cmdb_hostname"]


async def test_admin_password_reset_no_email(client, db, admin, admin_headers):
    from tests.conftest import make_user

    u = await make_user(db, "reset@example.com", GlobalRole.viewer)
    await db.commit()
    r = await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "brandNew123"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    await db.refresh(u)
    assert verify_password("brandNew123", u.hashed_password)


async def test_password_reset_requires_admin(client, db, viewer, viewer_headers):
    r = await client.post(
        f"/api/v1/users/{viewer.id}/reset-password",
        json={"new_password": "brandNew123"},
        headers=viewer_headers,
    )
    assert r.status_code == 403


async def test_password_reset_min_length_422(client, admin, admin_headers):
    r = await client.post(
        f"/api/v1/users/{admin.id}/reset-password",
        json={"new_password": "short"},
        headers=admin_headers,
    )
    assert r.status_code == 422


async def test_users_numbered_pagination(client, db, admin, admin_headers):
    from tests.conftest import make_user

    for i in range(25):
        await make_user(db, f"pg{i}@example.com", GlobalRole.viewer)
    await db.commit()
    r = await client.get("/api/v1/users?page=1&page_size=10", headers=admin_headers)
    data = r.json()
    assert len(data["data"]) == 10
    assert data["meta"]["total"] >= 26 and data["meta"]["page"] == 1
    assert data["meta"]["pages"] >= 3
    r2 = await client.get("/api/v1/users?page=2&page_size=10", headers=admin_headers)
    ids1 = {u["id"] for u in data["data"]}
    ids2 = {u["id"] for u in r2.json()["data"]}
    assert ids1.isdisjoint(ids2)  # distinct pages


async def test_per_user_history_via_actor_filter(client, db, admin, admin_headers):
    # admin reset a user's password -> audit row with actor_id=admin shows in history
    from tests.conftest import make_user

    u = await make_user(db, "hist@example.com", GlobalRole.viewer)
    await db.commit()
    await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "brandNew123"},
        headers=admin_headers,
    )
    hist = await client.get(f"/api/v1/audit-logs?actor_id={admin.id}", headers=admin_headers)
    assert "reset_password" in [e["action"] for e in hist.json()["data"]]
