"""DB-backed correlation config: seeded defaults, admin-only edits, audited."""


async def test_get_config_returns_seeded_defaults(client, viewer_headers):
    res = await client.get("/api/v1/correlation-config", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["dedup_window_seconds"] == 300
    assert data["correlation_window_seconds"] == 900
    assert data["group_attrs"] == ["host", "service", "cluster"]


async def test_admin_can_update_config_and_change_is_audited(client, admin_headers):
    res = await client.patch(
        "/api/v1/correlation-config",
        json={"dedup_window_seconds": 600, "group_attrs": ["service", "host"]},
        headers=admin_headers,
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["dedup_window_seconds"] == 600
    assert data["correlation_window_seconds"] == 900  # untouched field kept
    assert data["group_attrs"] == ["service", "host"]

    # persisted
    again = await client.get("/api/v1/correlation-config", headers=admin_headers)
    assert again.json()["data"]["dedup_window_seconds"] == 600

    logs = await client.get(
        "/api/v1/audit-logs?resource_type=correlation_config", headers=admin_headers
    )
    entries = logs.json()["data"]
    assert len(entries) == 1
    assert entries[0]["action"] == "update"
    assert entries[0]["before"]["dedup_window_seconds"] == 300
    assert entries[0]["after"]["dedup_window_seconds"] == 600


async def test_non_admin_cannot_update_config(client, editor_headers, viewer_headers):
    for headers in (editor_headers, viewer_headers):
        res = await client.patch(
            "/api/v1/correlation-config",
            json={"dedup_window_seconds": 60},
            headers=headers,
        )
        assert res.status_code == 403


async def test_invalid_values_rejected(client, admin_headers):
    for payload in (
        {"dedup_window_seconds": 0},
        {"dedup_window_seconds": -5},
        {"correlation_window_seconds": 0},
        {"group_attrs": []},
    ):
        res = await client.patch("/api/v1/correlation-config", json=payload, headers=admin_headers)
        assert res.status_code == 422, payload
