"""IMP overhaul — endpoint<->frontend CONTRACT verification.

Replays the EXACT request shapes the React frontend sends (query params, JSON
bodies, pagination + date-range + sentinel handling) against the real ASGI app,
and asserts the response shape matches what the TS interfaces consume. Targets
the four bug classes that slipped past "all green" before:

  (a) query-param sentinel / enum parsing  (status=__all__, group_by, in_incident)
  (b) Pydantic <-> TS nullable mismatch     (every nullable field must serialize
      to null without a 500, and every TS-required field must be present)
  (c) pagination params (?page=&page_size=) frontend vs API
  (d) date-range start/end (ISO-UTC) end-to-end

The frontend api client drops undefined/"" params before they hit the wire, so a
sentinel like "__all__" is mapped to undefined in the page and never sent — these
tests send the post-drop shape (what actually reaches FastAPI).
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.api.v1.labels import get_query_client
from app.api.v1.notifications import get_alertmanager_client
from app.main import app
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow
from app.models.group import Group
from app.models.mimir import MimirRule
from app.models.user import GlobalRole

pytestmark = pytest.mark.asyncio

L2 = "L2TEST"  # the editor/viewer fixtures map to this l2
NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _assert_keys(obj: dict, required: set[str], where: str):
    """Every TS-required field must be present (key exists, value may be null)."""
    missing = required - obj.keys()
    assert not missing, f"{where}: response missing TS-required keys {missing}"


# ---------- seed ----------
@pytest_asyncio.fixture
async def seeded(db):
    # Incident timestamps are anchored to the real clock so the graph's
    # last_seen >= now-window filter includes it; the member alerts keep their
    # NOW-relative received_at (independent — used by the date-range test).
    real_now = utcnow()
    inc = Incident(
        title="svc L2TEST degraded",
        status=IncidentStatus.open,
        severity="critical",
        group_key=L2,
        first_seen=real_now,
        last_seen=real_now,
        alert_count=2,
        origin="auto",
        cmdb_service_l2_code=L2,
    )
    db.add(inc)
    await db.flush()
    alerts = []
    for i in range(2):
        a = AlertEvent(
            fingerprint=f"fp{i}",
            source="alertmanager",
            name="HostHighCpuLoad",
            severity="critical",
            status="firing",
            labels={"cmdb_service_l2_code": L2},
            annotations={},
            starts_at=NOW,
            received_at=NOW - timedelta(hours=i),
            incident_id=inc.id,
            cmdb_ci=f"CS-{i}",
            cmdb_hostname=f"host-{i}",
            cmdb_zone="Z1",
            client_address="10.0.0.1",
            cmdb_service_l1_code="L1",
            cmdb_service_l2_code=L2,
            value=95.0,
        )
        alerts.append(a)
        db.add(a)
    await db.commit()
    return {"incident": inc, "alerts": alerts}


# ====================== (a) sentinel / enum parsing ======================
async def test_incidents_status_active_sentinel_and_all(client, seeded, admin_headers):
    # ACTIVE = "open,acknowledged" (comma-joined enum) — must NOT 422
    r = await client.get(
        "/api/v1/incidents?status=open,acknowledged&limit=20", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    # ALL sentinel -> frontend drops the param entirely (no status= on the wire)
    r2 = await client.get("/api/v1/incidents?limit=20", headers=admin_headers)
    assert r2.status_code == 200 and len(r2.json()["data"]) == 1
    # a single status value also parses
    r3 = await client.get("/api/v1/incidents?status=resolved", headers=admin_headers)
    assert r3.status_code == 200 and r3.json()["data"] == []


async def test_alerts_group_by_enum_and_invalid(client, seeded, admin_headers):
    r = await client.get("/api/v1/alerts?group_by=client_address", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"][0] == {"value": "10.0.0.1", "count": 2}
    # an out-of-set group_by (e.g. cmdb_ci is filter-only, not group-by) -> 422
    bad = await client.get("/api/v1/alerts?group_by=cmdb_ci", headers=admin_headers)
    assert bad.status_code == 422


async def test_alerts_in_incident_bool_string(client, seeded, admin_headers):
    # frontend sends in_incident="true"/"false" (FastAPI bool coercion)
    yes = await client.get("/api/v1/alerts?in_incident=true", headers=admin_headers)
    assert yes.status_code == 200 and len(yes.json()["data"]) == 2
    no = await client.get("/api/v1/alerts?in_incident=false", headers=admin_headers)
    assert no.status_code == 200 and no.json()["data"] == []


async def test_graph_status_enum(client, seeded, admin_headers):
    r = await client.get(
        "/api/v1/graph?window_hours=24&status=open,acknowledged&max_lanes=200",
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(data.keys()) == {"incidents", "meta"}
    lane = data["incidents"][0]
    _assert_keys(
        lane,
        {
            "id",
            "title",
            "severity",
            "status",
            "first_seen",
            "last_seen",
            "alert_count",
            "cmdb_service_l2_code",
            "alerts",
        },
        "GraphIncident",
    )
    _assert_keys(
        lane["alerts"][0],
        {"id", "name", "severity", "status", "received_at", "cmdb_hostname", "dedup_count"},
        "GraphAlert",
    )
    assert set(data["meta"].keys()) == {"truncated", "total_incidents"}


# ====================== (b) nullable: shapes serialize without 500 ======================
async def test_stored_alert_shape(client, seeded, admin_headers):
    r = await client.get("/api/v1/alerts?limit=50", headers=admin_headers)
    assert r.status_code == 200
    a = r.json()["data"][0]
    _assert_keys(
        a,
        {
            "id",
            "fingerprint",
            "source",
            "name",
            "severity",
            "status",
            "labels",
            "annotations",
            "starts_at",
            "received_at",
            "dedup_count",
            "incident_id",
            "cmdb_ci",
            "cmdb_hostname",
            "cmdb_zone",
            "client_address",
            "cmdb_service_l1_code",
            "cmdb_service_l2_code",
            "value",
            "suppressed",
            "correlated",
        },
        "StoredAlert",
    )


async def test_incident_detail_shape(client, seeded, admin_headers):
    inc_id = seeded["incident"].id
    r = await client.get(f"/api/v1/incidents/{inc_id}", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()["data"]
    _assert_keys(
        d,
        {
            "id",
            "title",
            "status",
            "severity",
            "group_key",
            "first_seen",
            "last_seen",
            "alert_count",
            "created_at",
            "origin",
            "cmdb_service_l2_code",
            "cmdb_service_l1_code",
            "cmdb_zone",
            "notify_email",
            "notify_telegram",
            "notify_oncall",
            "grouping_rule_id",
            "alerts",
            "timeline",
        },
        "IncidentDetail",
    )


async def test_pulled_rule_nullable_fields(client, db, admin_headers):
    """PulledRule.for_seconds/severity/health/state are nullable in the model;
    the API must return null (not 500) and the key must still be present so the
    TS (now nullable) renders. This is the exact (b)-class mismatch."""
    db.add(
        MimirRule(
            alertname="NullishRule",
            expr="",
            for_seconds=None,
            severity=None,
            health=None,
            state=None,
            last_error=None,
            value=None,
            base_threshold=None,
            comparator=None,
            synced_at=utcnow(),
        )
    )
    await db.commit()
    r = await client.get("/api/v1/rules/pulled", headers=admin_headers)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["data"] if x["alertname"] == "NullishRule")
    for k in (
        "for_seconds",
        "severity",
        "health",
        "state",
        "last_error",
        "value",
        "base_threshold",
        "comparator",
        "last_evaluation",
        "synced_at",
    ):
        assert k in row, f"PulledRule missing {k}"
    assert row["for_seconds"] is None and row["severity"] is None
    assert row["health"] is None and row["state"] is None


# ====================== (c) numbered pagination params ======================
async def test_users_numbered_pagination_contract(client, db, admin, admin_headers):
    from tests.conftest import make_user

    for i in range(25):
        await make_user(db, f"cu{i}@example.com", GlobalRole.viewer)
    await db.commit()
    # frontend sends page + page_size as STRINGS
    r = await client.get("/api/v1/users?page=1&page_size=20", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["data"]) == 20
    _assert_keys(body["meta"], {"total", "page", "pages", "page_size"}, "Meta(numbered)")
    assert body["meta"]["page"] == 1 and body["meta"]["page_size"] == 20
    assert body["meta"]["total"] >= 26 and body["meta"]["pages"] >= 2


async def test_audit_numbered_pagination_contract(client, db, admin, admin_headers):
    # generate audit rows via a real write path (password resets)
    from tests.conftest import make_user

    u = await make_user(db, "auditee@example.com", GlobalRole.viewer)
    await db.commit()
    for _ in range(3):
        await client.post(
            f"/api/v1/users/{u.id}/reset-password",
            json={"new_password": "brandNew123"},
            headers=admin_headers,
        )
    r = await client.get("/api/v1/audit-logs?page=1&page_size=25", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    _assert_keys(body["meta"], {"total", "page", "pages", "page_size"}, "Meta(numbered)")
    a = body["data"][0]
    _assert_keys(
        a,
        {
            "id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "before",
            "after",
            "ip",
            "emergency",
            "created_at",
        },
        "AuditLog",
    )


async def test_user_history_actor_filter_cursor_mode(client, db, admin, admin_headers):
    # the user-history dialog sends actor_id + page_size but NO page -> cursor mode
    from tests.conftest import make_user

    u = await make_user(db, "hist2@example.com", GlobalRole.viewer)
    await db.commit()
    await client.post(
        f"/api/v1/users/{u.id}/reset-password",
        json={"new_password": "brandNew123"},
        headers=admin_headers,
    )
    r = await client.get(
        f"/api/v1/audit-logs?actor_id={admin.id}&page_size=25", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert "reset_password" in [e["action"] for e in r.json()["data"]]


# ====================== (d) date-range end-to-end ======================
async def test_alerts_date_range_iso_utc(client, seeded, admin_headers):
    """Frontend DateRangePicker emits full ISO-UTC (…Z) start/end. The window
    [start,end) must bound received_at correctly (one seeded alert is 1h old)."""
    end = (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    # start after the older alert (received_at = NOW-1h) -> only the NOW alert
    start = (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    r = await client.get(f"/api/v1/alerts?start={start}&end={end}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    # widen the window -> both alerts
    wide_start = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    r2 = await client.get(f"/api/v1/alerts?start={wide_start}&end={end}", headers=admin_headers)
    assert len(r2.json()["data"]) == 2


async def test_stats_trend_and_hosts_shape(client, seeded, admin_headers):
    tr = await client.get("/api/v1/stats/trend?hours=24", headers=admin_headers)
    assert tr.status_code == 200
    body = tr.json()["data"]
    assert "bucket_seconds" in body and isinstance(body["buckets"], list)
    _assert_keys(body["buckets"][0], {"bucket", "critical", "warning", "info"}, "TrendBucket")
    h = await client.get("/api/v1/stats/hosts?since_hours=168", headers=admin_headers)
    assert h.status_code == 200
    if h.json()["data"]:
        _assert_keys(
            h.json()["data"][0],
            {"host", "open", "total", "alerts", "max_severity", "last_seen"},
            "HostStat",
        )


# ====================== channel assignment (Stage 7) ======================
async def test_group_channels_crud_contract(client, db, admin, admin_headers):
    g = Group(name="ch-team")
    db.add(g)
    await db.commit()
    # telegram requires bot_token + chat_id (model_validator)
    r = await client.post(
        f"/api/v1/groups/{g.id}/channels",
        json={"channel": "telegram", "bot_token": "123:abc", "chat_id": "-100"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    gc = r.json()["data"]
    _assert_keys(
        gc,
        {
            "id",
            "channel",
            "enabled",
            "chat_id",
            "email",
            "bot_token",
            "webhook_url",
            "oncall_token",
        },
        "GroupChannel",
    )
    assert gc["bot_token"] == "********"  # secret MASKED, never echoed
    # invalid telegram (missing chat_id) -> 422 from the schema validator
    bad = await client.post(
        f"/api/v1/groups/{g.id}/channels",
        json={"channel": "telegram", "bot_token": "x"},
        headers=admin_headers,
    )
    assert bad.status_code == 422
    # list + delete
    lst = await client.get(f"/api/v1/groups/{g.id}/channels", headers=admin_headers)
    assert lst.status_code == 200 and len(lst.json()["data"]) == 1
    d = await client.delete(f"/api/v1/channels/{gc['id']}", headers=admin_headers)
    assert d.status_code == 200


# ====================== threshold overrides (Stage 2/3) ======================
async def test_threshold_override_contract(client, db, editor, editor_headers):
    # server-targeted (cmdb_ci) override
    r = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "HostHighCpuLoad", "target_cmdb_ci": "CS-0", "value": 90.0},
        headers=editor_headers,
    )
    assert r.status_code == 201, r.text
    o = r.json()["data"]
    _assert_keys(
        o,
        {"id", "alertname", "target_cmdb_ci", "target_label_key", "target_label_value", "value"},
        "ThresholdOverride",
    )
    # label-targeted override
    r2 = await client.post(
        "/api/v1/threshold-overrides",
        json={
            "alertname": "HostHighCpuLoad",
            "target_label_key": "cmdb_service_l2_code",
            "target_label_value": L2,
            "value": 85.0,
        },
        headers=editor_headers,
    )
    assert r2.status_code == 201
    # neither target -> 422 (schema validator)
    bad = await client.post(
        "/api/v1/threshold-overrides",
        json={"alertname": "X", "value": 1.0},
        headers=editor_headers,
    )
    assert bad.status_code == 422
    # patch the number
    p = await client.patch(
        f"/api/v1/threshold-overrides/{o['id']}", json={"value": 70.0}, headers=editor_headers
    )
    assert p.status_code == 200 and p.json()["data"]["value"] == 70.0


# ====================== silences (Stage 6) — server-built matcher ======================
async def test_silence_read_and_write_contract(client, db, admin, admin_headers):
    class FakeAM:
        def __init__(self):
            self.store = []

        async def create_silence(self, payload):
            self.store.append(payload)
            return "sil-new"

        async def delete_silence(self, sid):
            self.store = []

        async def get_silences(self):
            return [
                {
                    "id": "sil-new",
                    "status": {"state": "active"},
                    "matchers": [
                        {
                            "name": "cmdb_service_l2_code",
                            "value": L2,
                            "isRegex": False,
                            "isEqual": True,
                        }
                    ],
                    "startsAt": "2026-06-22T10:00:00Z",
                    "endsAt": "2026-06-22T14:00:00Z",
                    "comment": "maint",
                    "createdBy": "admin",
                }
            ]

        async def aclose(self):
            pass

    fake = FakeAM()
    app.dependency_overrides[get_alertmanager_client] = lambda: fake
    try:
        # service-targeted silence: user picks "service" + the l2 value; atlas builds matcher
        r = await client.post(
            "/api/v1/silences",
            json={
                "target_kind": "service",
                "target_value": L2,
                "starts_at": "2026-06-22T10:00:00+00:00",
                "ends_at": "2026-06-22T14:00:00+00:00",
                "comment": "maintenance",
            },
            headers=admin_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["matcher"]["name"] == "cmdb_service_l2_code"
        # ends<=starts -> 400
        bad = await client.post(
            "/api/v1/silences",
            json={
                "target_kind": "server",
                "target_value": "CS-0",
                "starts_at": "2026-06-22T14:00:00+00:00",
                "ends_at": "2026-06-22T10:00:00+00:00",
                "comment": "x",
            },
            headers=admin_headers,
        )
        assert bad.status_code == 400
        # read cache shape
        lst = await client.get("/api/v1/silences", headers=admin_headers)
        assert lst.status_code == 200
        s = lst.json()["data"][0]
        _assert_keys(
            s,
            {
                "silence_id",
                "matchers",
                "starts_at",
                "ends_at",
                "comment",
                "created_by_label",
                "state",
            },
            "Silence",
        )
    finally:
        app.dependency_overrides.pop(get_alertmanager_client, None)


# ====================== labels proxy (autocomplete contract) ======================
async def test_labels_proxy_contract(client, admin_headers):
    class FakeQ:
        async def label_names(self, **kw):
            return ["cmdb_hostname", "cmdb_zone", "cmdb_ci", "client_address"]

        async def label_values(self, name, **kw):
            return [f"{name}-a", f"{name}-b"]

        async def aclose(self):
            pass

    app.dependency_overrides[get_query_client] = lambda: FakeQ()
    try:
        names = await client.get("/api/v1/labels", headers=admin_headers)
        assert names.status_code == 200
        assert "cmdb_hostname" in names.json()["data"]
        vals = await client.get("/api/v1/labels/cmdb_hostname/values", headers=admin_headers)
        assert vals.status_code == 200 and vals.json()["data"] == [
            "cmdb_hostname-a",
            "cmdb_hostname-b",
        ]
    finally:
        app.dependency_overrides.pop(get_query_client, None)


# ====================== groups: labels + description (Stage 8) ======================
async def test_group_labels_and_detail_contract(client, db, admin, admin_headers):
    g = Group(name="svc-grp")
    db.add(g)
    await db.commit()
    r = await client.patch(
        f"/api/v1/groups/{g.id}",
        json={"description": "core platform", "labels": ["cmdb_zone", "cmdb_hostname"]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    _assert_keys(
        body, {"id", "name", "description", "labels", "created_at", "member_count"}, "Group"
    )
    assert body["labels"] == ["cmdb_zone", "cmdb_hostname"]
    detail = await client.get(f"/api/v1/groups/{g.id}", headers=admin_headers)
    assert detail.json()["data"]["labels"] == ["cmdb_zone", "cmdb_hostname"]


# ====================== incident lifecycle (Stage 5) ======================
async def test_detach_last_alert_409_then_delete_dissolves(client, db, editor, editor_headers):
    inc = Incident(
        title="lone",
        status=IncidentStatus.open,
        severity="warning",
        group_key=L2,
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
        origin="manual",
        cmdb_service_l2_code=L2,
    )
    db.add(inc)
    await db.flush()
    a = AlertEvent(
        fingerprint="lone",
        source="alertmanager",
        name="X",
        severity="warning",
        status="firing",
        labels={"cmdb_service_l2_code": L2},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        incident_id=inc.id,
        cmdb_service_l2_code=L2,
    )
    db.add(a)
    await db.commit()
    # detaching the LAST alert is forbidden (A4)
    r = await client.delete(f"/api/v1/incidents/{inc.id}/alerts/{a.id}", headers=editor_headers)
    assert r.status_code == 409, r.text
    # deleting the incident dissolves it + frees the alert
    d = await client.delete(f"/api/v1/incidents/{inc.id}", headers=editor_headers)
    assert d.status_code == 200
    assert d.json()["data"]["freed_alerts"] == 1
    # alert survives, incident_id cleared
    got = await client.get(f"/api/v1/alerts/{a.id}", headers=editor_headers)
    assert got.status_code == 200 and got.json()["data"]["incident_id"] is None
