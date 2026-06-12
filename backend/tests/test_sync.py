from app.services.rule_sync import payload_checksum, serialize_rule_group


async def make_rule(client, headers, name="R1", **overrides):
    payload = {
        "name": name,
        "scope_type": "global",
        "expr": "up == 0",
        "for_duration": "1m",
        "severity": "critical",
        "annotations": {"summary": "down"},
    }
    payload.update(overrides)
    res = await client.post("/api/v1/rules", json=payload, headers=headers)
    return res.json()["data"]["id"]


async def test_rule_group_crud_and_sync(client, admin_headers, fake_ruler):
    rule_id = await make_rule(client, admin_headers)
    created = await client.post(
        "/api/v1/rule-groups",
        json={
            "name": "core-alerts",
            "namespace": "atlas",
            "interval": "1m",
            "rule_ids": [rule_id],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    group_id = created.json()["data"]["id"]
    assert created.json()["data"]["rule_count"] == 1

    synced = await client.post(
        f"/api/v1/rule-groups/{group_id}/sync", headers=admin_headers
    )
    assert synced.status_code == 200
    assert len(fake_ruler.pushed) == 1
    namespace, payload = fake_ruler.pushed[0]
    assert namespace == "atlas"
    assert payload["name"] == "core-alerts"
    assert payload["rules"][0]["alert"] == "R1"
    assert payload["rules"][0]["expr"] == "up == 0"
    assert payload["rules"][0]["labels"]["severity"] == "critical"

    state = await client.get("/api/v1/sync-state", headers=admin_headers)
    targets = {s["target"]: s["status"] for s in state.json()["data"]}
    assert targets["ruler"] == "ok"


async def test_disabled_rules_excluded_from_payload(client, admin_headers, fake_ruler):
    rule_id = await make_rule(client, admin_headers, name="ToDisable")
    group = await client.post(
        "/api/v1/rule-groups",
        json={"name": "g1", "namespace": "ns", "rule_ids": [rule_id]},
        headers=admin_headers,
    )
    group_id = group.json()["data"]["id"]
    await client.post(f"/api/v1/rules/{rule_id}/disable", headers=admin_headers)

    await client.post(f"/api/v1/rule-groups/{group_id}/sync", headers=admin_headers)
    _, payload = fake_ruler.pushed[-1]
    assert payload["rules"] == []


async def test_emergency_apply(client, admin_headers, fake_ruler):
    rule_id = await make_rule(client, admin_headers, name="Urgent")
    res = await client.post(
        "/api/v1/rules/emergency-apply",
        json={"rule_id": rule_id, "reason": "production incident #123"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["data"]["pushed"] is True
    namespace, payload = fake_ruler.pushed[0]
    assert namespace == "emergency"
    assert payload["rules"][0]["alert"] == "Urgent"

    logs = await client.get("/api/v1/audit-logs?emergency=true", headers=admin_headers)
    entries = logs.json()["data"]
    assert len(entries) == 1
    assert entries[0]["action"] == "emergency_apply"
    assert entries[0]["after"]["reason"] == "production incident #123"


async def test_emergency_apply_invalid_expr_rejected(client, admin_headers, fake_ruler):
    rule_id = await make_rule(
        client, admin_headers, name="Broken", expr="sum(rate(x[1m])"
    )
    res = await client.post(
        "/api/v1/rules/emergency-apply",
        json={"rule_id": rule_id, "reason": "x"},
        headers=admin_headers,
    )
    assert res.status_code == 422
    assert fake_ruler.pushed == []


async def test_viewer_cannot_emergency_apply(
    client, admin_headers, viewer_headers, fake_ruler
):
    rule_id = await make_rule(client, admin_headers)
    res = await client.post(
        "/api/v1/rules/emergency-apply",
        json={"rule_id": rule_id, "reason": "x"},
        headers=viewer_headers,
    )
    assert res.status_code == 403


async def test_sync_all_checksum_skips_unchanged(db, admin):
    from app.models import AlertRule, RuleGroup, RuleGroupRule
    from app.models.rule import Datasource, ScopeType, Severity
    from app.services.rule_sync import sync_all_rule_groups
    from tests.conftest import FakeRuler

    rule = AlertRule(
        name="R",
        scope_type=ScopeType.global_,
        expr="up == 0",
        for_duration="1m",
        severity=Severity.info,
        labels={},
        annotations={},
        enabled=True,
        datasource=Datasource.metrics,
    )
    group = RuleGroup(name="g", namespace="ns", interval="1m")
    db.add_all([rule, group])
    await db.flush()
    db.add(RuleGroupRule(rule_group_id=group.id, alert_rule_id=rule.id, order=0))
    await db.commit()

    ruler = FakeRuler()
    state = await sync_all_rule_groups(db, ruler)
    await db.commit()
    assert state.status.value == "ok"
    assert len(ruler.pushed) == 1

    # Unchanged content: checksum match short-circuits the push.
    await sync_all_rule_groups(db, ruler)
    assert len(ruler.pushed) == 1


async def test_sync_failure_marks_state_failed(db, admin):
    from app.models import RuleGroup
    from app.services.rule_sync import sync_all_rule_groups
    from tests.conftest import FakeRuler

    db.add(RuleGroup(name="g", namespace="ns", interval="1m"))
    await db.commit()

    state = await sync_all_rule_groups(db, FakeRuler(fail=True))
    assert state.status.value == "failed"
    assert "ruler down" in state.last_error


def test_serialize_group_orders_rules():
    class L:
        def __init__(self, order, rule):
            self.order = order
            self.rule = rule

    class R:
        def __init__(self, name):
            self.name = name
            self.expr = "up"
            self.for_duration = "1m"
            self.labels = {}
            self.annotations = {}
            self.enabled = True

            class Sev:
                value = "info"

            self.severity = Sev()

    class G:
        name = "g"
        interval = "1m"
        rule_links = [L(1, R("second")), L(0, R("first"))]

    payload = serialize_rule_group(G())
    assert [r["alert"] for r in payload["rules"]] == ["first", "second"]
    assert payload_checksum(payload) == payload_checksum(payload)
