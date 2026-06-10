async def test_login_success(client, admin):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is None
    assert body["data"]["access_token"]
    assert "atlas_refresh" in res.cookies


async def test_login_wrong_password(client, admin):
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "http_401"


async def test_login_rate_limited(client, admin):
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password"},
        )
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    assert res.status_code == 429


async def test_me_requires_token(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401


async def test_me(client, admin, admin_headers):
    res = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["data"]["email"] == "admin@example.com"
    assert res.json()["data"]["role"] == "admin"


async def test_refresh_flow(client, admin):
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    res = await client.post("/api/v1/auth/refresh")
    assert res.status_code == 200
    assert res.json()["data"]["access_token"]


async def test_password_change(client, editor, editor_headers):
    res = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
        headers=editor_headers,
    )
    assert res.status_code == 200
    relogin = await client.post(
        "/api/v1/auth/login",
        json={"email": "editor@example.com", "password": "newpassword456"},
    )
    assert relogin.status_code == 200
