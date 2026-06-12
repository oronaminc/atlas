async def create_rule(client, headers, **overrides):
    payload = {
        "name": "HighCPU",
        "scope_type": "global",
        "expr": "avg(cpu_usage) > 0.9",
        "for_duration": "5m",
        "severity": "critical",
        "labels": {"team": "infra"},
        "annotations": {"summary": "CPU is high"},
    }
    payload.update(overrides)
    return await client.post("/api/v1/rules", json=payload, headers=headers)


async def test_rule_crud(client, admin_headers):
    created = await create_rule(client, admin_headers)
    assert created.status_code == 201
    rule_id = created.json()["data"]["id"]

    fetched = await client.get(f"/api/v1/rules/{rule_id}", headers=admin_headers)
    assert fetched.json()["data"]["name"] == "HighCPU"

    patched = await client.patch(
        f"/api/v1/rules/{rule_id}", json={"severity": "warning"}, headers=admin_headers
    )
    assert patched.json()["data"]["severity"] == "warning"

    disabled = await client.post(
        f"/api/v1/rules/{rule_id}/disable", headers=admin_headers
    )
    assert disabled.json()["data"]["enabled"] is False
    enabled = await client.post(
        f"/api/v1/rules/{rule_id}/enable", headers=admin_headers
    )
    assert enabled.json()["data"]["enabled"] is True

    deleted = await client.delete(f"/api/v1/rules/{rule_id}", headers=admin_headers)
    assert deleted.status_code == 200


async def test_rule_filters(client, admin_headers):
    await create_rule(client, admin_headers, name="A", severity="critical")
    await create_rule(client, admin_headers, name="B", severity="info")

    res = await client.get("/api/v1/rules?severity=info", headers=admin_headers)
    assert [r["name"] for r in res.json()["data"]] == ["B"]

    res = await client.get("/api/v1/rules?scope_type=global", headers=admin_headers)
    assert len(res.json()["data"]) == 2


async def test_invalid_duration_rejected(client, admin_headers):
    res = await create_rule(client, admin_headers, for_duration="5 minutes")
    assert res.status_code == 422


async def test_editor_cannot_create_global_rule(client, editor_headers):
    res = await create_rule(client, editor_headers)
    assert res.status_code == 403


async def test_editor_can_create_own_user_rule(client, editor, editor_headers):
    res = await create_rule(
        client,
        editor_headers,
        scope_type="user",
        scope_ref_id=str(editor.id),
        name="MyRule",
    )
    assert res.status_code == 201


async def test_user_rule_protected_from_other_editor(client, db, editor_headers, admin):
    from app.models.user import GlobalRole
    from tests.conftest import auth_headers, make_user

    other = await make_user(db, "other@example.com", GlobalRole.editor)
    created = await create_rule(
        client,
        auth_headers(other),
        scope_type="user",
        scope_ref_id=str(other.id),
        name="OtherRule",
    )
    rule_id = created.json()["data"]["id"]

    res = await client.patch(
        f"/api/v1/rules/{rule_id}", json={"name": "Hijacked"}, headers=editor_headers
    )
    assert res.status_code == 403

    res = await client.patch(
        f"/api/v1/rules/{rule_id}",
        json={"name": "AdminEdit"},
        headers=auth_headers(admin),
    )
    assert res.status_code == 200


async def test_validate_rule(client, admin_headers):
    good = await create_rule(client, admin_headers, name="Good")
    rule_id = good.json()["data"]["id"]
    res = await client.post(f"/api/v1/rules/{rule_id}/validate", headers=admin_headers)
    assert res.json()["data"]["valid"] is True

    bad = await create_rule(client, admin_headers, name="Bad", expr="sum(rate(x[5m])")
    bad_id = bad.json()["data"]["id"]
    res = await client.post(f"/api/v1/rules/{bad_id}/validate", headers=admin_headers)
    assert res.json()["data"]["valid"] is False
    assert res.json()["data"]["errors"]


async def test_rule_mutation_creates_audit_log(client, admin_headers):
    created = await create_rule(client, admin_headers, name="Audited")
    rule_id = created.json()["data"]["id"]
    res = await client.get(
        f"/api/v1/audit-logs?resource_type=alert_rule&resource_id={rule_id}",
        headers=admin_headers,
    )
    logs = res.json()["data"]
    assert len(logs) == 1
    assert logs[0]["action"] == "create"
    assert logs[0]["after"]["name"] == "Audited"
