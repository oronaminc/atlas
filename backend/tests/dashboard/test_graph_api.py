"""Incident swimlane graph: lane-per-incident with member alerts inline,
window+status filter, truncation, expansion, auth."""

from datetime import timedelta

from app.models.alerting import AlertEvent, IncidentStatus
from app.models.base import utcnow
from tests.notifications.helpers import seed_incident


async def seed_graph(db):
    now = utcnow()
    a = await seed_incident(db, severity="critical", title="HighCPU on web-01")
    a.first_seen = now - timedelta(minutes=10)
    a.last_seen = now
    b = await seed_incident(db, severity="warning", title="DiskFull on web-01")
    b.first_seen = now - timedelta(minutes=5)
    b.last_seen = now
    old = await seed_incident(db, severity="info", title="old resolved")
    old.status = IncidentStatus.resolved
    old.first_seen = now - timedelta(hours=30)
    old.last_seen = now - timedelta(hours=30)
    for incident, name, n in ((a, "HighCPU", 2), (b, "DiskFull", 1)):
        for j in range(n):
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
                    received_at=incident.first_seen + timedelta(minutes=j),
                    incident_id=incident.id,
                    cmdb_hostname="web-01",
                    cmdb_service_l2_code="L2TEST",
                )
            )
    await db.commit()
    return a, b, old


async def test_graph_incident_lanes_with_alerts(client, db, viewer_headers):
    a, b, old = await seed_graph(db)
    data = (await client.get("/api/v1/graph", headers=viewer_headers)).json()["data"]
    lanes = {lane["id"]: lane for lane in data["incidents"]}
    # default open+acknowledged, 24h -> 'old' (resolved, 30h) excluded
    assert set(lanes) == {str(a.id), str(b.id)}
    assert lanes[str(a.id)]["title"] == "HighCPU on web-01"
    assert len(lanes[str(a.id)]["alerts"]) == 2  # member alerts inline
    assert lanes[str(a.id)]["alerts"][0]["name"] == "HighCPU"
    assert data["meta"]["truncated"] is False


async def test_graph_status_window_filter(client, db, viewer_headers):
    _, _, old = await seed_graph(db)
    data = (
        await client.get("/api/v1/graph?window_hours=72&status=resolved", headers=viewer_headers)
    ).json()["data"]
    assert [lane["id"] for lane in data["incidents"]] == [str(old.id)]


async def test_graph_truncation(client, db, viewer_headers):
    await seed_graph(db)
    data = (await client.get("/api/v1/graph?max_lanes=1", headers=viewer_headers)).json()["data"]
    assert data["meta"]["truncated"] is True
    assert len(data["incidents"]) == 1


async def test_graph_incident_expansion(client, db, viewer_headers):
    a, *_ = await seed_graph(db)
    data = (await client.get(f"/api/v1/graph/incident/{a.id}", headers=viewer_headers)).json()[
        "data"
    ]
    assert len(data["alerts"]) == 2
    assert all(al["name"] == "HighCPU" for al in data["alerts"])


async def test_graph_requires_auth(client):
    assert (await client.get("/api/v1/graph")).status_code == 401
