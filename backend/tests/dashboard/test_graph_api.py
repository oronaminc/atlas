"""Graph endpoint: node/edge derivation, window+status filters, truncation,
expansion, auth."""

from datetime import timedelta

from app.models.alerting import AlertEvent, IncidentStatus
from app.models.base import utcnow
from tests.notifications.helpers import seed_incident


async def seed_graph(db):
    now = utcnow()
    a = await seed_incident(db, severity="critical", title="HighCPU on web-01")
    a.group_key = "host=web-01"
    a.first_seen = now - timedelta(minutes=10)
    a.last_seen = now
    b = await seed_incident(db, severity="warning", title="DiskFull on web-01")
    b.group_key = "host=web-01"
    b.first_seen = now - timedelta(minutes=5)
    b.last_seen = now
    c = await seed_incident(db, severity="warning", title="HighCPU on db-01")
    c.group_key = "host=db-01"
    c.first_seen = now - timedelta(minutes=3)
    c.last_seen = now
    old = await seed_incident(db, severity="info", title="old resolved")
    old.group_key = "host=db-01"
    old.status = IncidentStatus.resolved
    old.first_seen = now - timedelta(hours=30)
    old.last_seen = now - timedelta(hours=30)

    # dominant names: a and c share "HighCPU" (cross-host), b is "DiskFull"
    for incident, name in ((a, "HighCPU"), (b, "DiskFull"), (c, "HighCPU")):
        for j in range(2):
            db.add(
                AlertEvent(
                    fingerprint=f"g-{incident.id.hex[:6]}-{j}",
                    source="alertmanager",
                    name=name,
                    severity=incident.severity,
                    status="firing",
                    labels={},
                    annotations={},
                    starts_at=incident.first_seen,
                    received_at=incident.first_seen,
                    incident_id=incident.id,
                )
            )
    await db.commit()
    return a, b, c, old


async def test_graph_nodes_and_edges(client, db, viewer_headers):
    a, b, c, old = await seed_graph(db)
    res = await client.get("/api/v1/graph", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]

    by_kind = {}
    for node in data["nodes"]:
        by_kind.setdefault(node["kind"], []).append(node)
    # default filter: open+acknowledged, 24h -> 'old' excluded
    assert len(by_kind["incident"]) == 3
    assert {h["id"] for h in by_kind["host"]} == {"host=web-01", "host=db-01"}
    incident_node = next(n for n in by_kind["incident"] if n["id"] == str(a.id))
    assert incident_node["severity"] == "critical"
    assert incident_node["dominant_name"] == "HighCPU"

    kinds = {}
    for edge in data["edges"]:
        kinds.setdefault(edge["kind"], []).append(edge)
    assert len(kinds["host"]) == 3
    # all three incidents are within the 900s window of each other -> 3 pairs
    assert len(kinds["temporal"]) == 3
    assert all(0 < e["weight"] <= 1 for e in kinds["temporal"])
    # a and c share dominant name across different hosts
    same_name_pairs = {frozenset((e["source"], e["target"])) for e in kinds["same_name"]}
    assert frozenset((str(a.id), str(c.id))) in same_name_pairs
    assert data["meta"]["truncated"] is False


async def test_graph_status_and_window_filters(client, db, viewer_headers):
    a, b, c, old = await seed_graph(db)
    res = await client.get("/api/v1/graph?window_hours=72&status=resolved", headers=viewer_headers)
    nodes = res.json()["data"]["nodes"]
    incident_ids = [n["id"] for n in nodes if n["kind"] == "incident"]
    assert incident_ids == [str(old.id)]


async def test_graph_truncation_meta(client, db, viewer_headers):
    await seed_graph(db)
    res = await client.get("/api/v1/graph?max_nodes=2", headers=viewer_headers)
    data = res.json()["data"]
    assert data["meta"]["truncated"] is True
    assert len([n for n in data["nodes"] if n["kind"] == "incident"]) == 2


async def test_graph_incident_expansion(client, db, viewer_headers):
    a, *_ = await seed_graph(db)
    res = await client.get(f"/api/v1/graph/incident/{a.id}", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data["nodes"]) == 2
    assert all(n["kind"] == "alert" and n["label"] == "HighCPU" for n in data["nodes"])
    assert all(e["kind"] == "member" and e["target"] == str(a.id) for e in data["edges"])


async def test_graph_requires_auth(client):
    assert (await client.get("/api/v1/graph")).status_code == 401
