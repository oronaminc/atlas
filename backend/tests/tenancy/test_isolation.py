"""Cross-tenant isolation: a tenant-A user gets ZERO tenant-B data on every
endpoint; HQ (tenant_id NULL) sees all tenants."""

from tests.conftest import auth_headers


async def test_incidents_list_is_tenant_scoped(client, world_a, world_b, a_viewer, b_viewer):
    res = await client.get("/api/v1/incidents", headers=auth_headers(a_viewer))
    titles = [i["title"] for i in res.json()["data"]]
    assert titles == ["HighCPU a"]

    res = await client.get("/api/v1/incidents", headers=auth_headers(b_viewer))
    titles = [i["title"] for i in res.json()["data"]]
    assert titles == ["HighCPU b"]


async def test_incident_detail_cross_tenant_404(client, world_a, world_b, a_viewer):
    other = world_b["incident"]
    res = await client.get(f"/api/v1/incidents/{other.id}", headers=auth_headers(a_viewer))
    assert res.status_code == 404
    mine = world_a["incident"]
    res = await client.get(f"/api/v1/incidents/{mine.id}", headers=auth_headers(a_viewer))
    assert res.status_code == 200


async def test_incident_actions_cross_tenant_404(client, world_a, world_b, a_editor):
    other = world_b["incident"]
    for verb in ("ack", "resolve", "suppress"):
        res = await client.post(
            f"/api/v1/incidents/{other.id}/{verb}", headers=auth_headers(a_editor)
        )
        assert res.status_code == 404, verb


async def test_stats_are_tenant_scoped(client, world_a, world_b, a_viewer):
    res = await client.get("/api/v1/stats/overview", headers=auth_headers(a_viewer))
    data = res.json()["data"]
    assert data["incidents"]["open"] == 1  # only A's incident
    assert data["alerts_24h"] == 0 or data["alerts_24h"] == 1  # only A's event window

    res = await client.get("/api/v1/stats/hosts", headers=auth_headers(a_viewer))
    rows = res.json()["data"]
    assert len(rows) == 1 and rows[0]["total"] == 1  # B's same-host incident invisible


async def test_graph_is_tenant_scoped(client, world_a, world_b, a_viewer, b_viewer):
    res = await client.get("/api/v1/graph?window_hours=720", headers=auth_headers(a_viewer))
    labels = [n["label"] for n in res.json()["data"]["nodes"] if n["kind"] == "incident"]
    assert labels == ["HighCPU a"]

    res = await client.get("/api/v1/graph?window_hours=720", headers=auth_headers(b_viewer))
    labels = [n["label"] for n in res.json()["data"]["nodes"] if n["kind"] == "incident"]
    assert labels == ["HighCPU b"]


async def test_notifications_list_is_tenant_scoped(client, world_a, world_b, a_viewer):
    res = await client.get("/api/v1/notifications", headers=auth_headers(a_viewer))
    rows = res.json()["data"]
    assert [r["recipient_address"] for r in rows] == ["chat-a"]


async def test_routes_and_groups_are_tenant_scoped(client, world_a, world_b, a_admin):
    res = await client.get("/api/v1/notification-routes", headers=auth_headers(a_admin))
    assert len(res.json()["data"]) == 1

    res = await client.get("/api/v1/groups", headers=auth_headers(a_admin))
    names = [g["name"] for g in res.json()["data"]]
    assert names == ["oncall-a"]


async def test_hq_sees_all_tenants(client, world_a, world_b, admin):
    # admin fixture has tenant_id NULL = HQ
    res = await client.get("/api/v1/incidents", headers=auth_headers(admin))
    titles = sorted(i["title"] for i in res.json()["data"])
    assert titles == ["HighCPU a", "HighCPU b"]

    res = await client.get("/api/v1/stats/overview", headers=auth_headers(admin))
    assert res.json()["data"]["incidents"]["open"] == 2

    res = await client.get("/api/v1/graph?window_hours=720", headers=auth_headers(admin))
    labels = sorted(n["label"] for n in res.json()["data"]["nodes"] if n["kind"] == "incident")
    assert labels == ["HighCPU a", "HighCPU b"]


async def test_hq_tenant_drilldown_param(client, world_a, world_b, admin, a_viewer):
    res = await client.get("/api/v1/incidents?tenant=sub-b", headers=auth_headers(admin))
    titles = [i["title"] for i in res.json()["data"]]
    assert titles == ["HighCPU b"]

    res = await client.get("/api/v1/stats/overview?tenant=sub-a", headers=auth_headers(admin))
    assert res.json()["data"]["incidents"]["open"] == 1

    res = await client.get("/api/v1/incidents?tenant=nope", headers=auth_headers(admin))
    assert res.status_code == 404

    # tenant users cannot escape their scope via the param
    res = await client.get("/api/v1/incidents?tenant=sub-b", headers=auth_headers(a_viewer))
    titles = [i["title"] for i in res.json()["data"]]
    assert titles == ["HighCPU a"]


async def test_audit_logs_tenant_scoped(client, world_a, world_b, a_editor, b_viewer, admin):
    incident = world_a["incident"]
    res = await client.post(f"/api/v1/incidents/{incident.id}/ack", headers=auth_headers(a_editor))
    assert res.status_code == 200
    # A's editor sees the audit row; B's viewer doesn't
    res = await client.get("/api/v1/audit-logs", headers=auth_headers(a_editor))
    actions = [e["action"] for e in res.json()["data"]]
    assert "ack" in actions
    res = await client.get("/api/v1/audit-logs", headers=auth_headers(b_viewer))
    assert all(e["action"] != "ack" for e in res.json()["data"])
    # HQ sees it
    res = await client.get("/api/v1/audit-logs", headers=auth_headers(admin))
    assert "ack" in [e["action"] for e in res.json()["data"]]
