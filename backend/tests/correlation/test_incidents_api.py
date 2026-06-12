"""Incident lifecycle API: list/detail/ack/resolve, RBAC, audit, timeline."""

from datetime import UTC, datetime

import pytest_asyncio

from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus

NOW = datetime(2026, 6, 10, 1, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def incident(db):
    inc = Incident(
        title="HighCPU on web-01",
        status=IncidentStatus.open,
        severity="critical",
        group_key="host=web-01",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
    )
    db.add(inc)
    await db.flush()
    db.add(
        AlertEvent(
            fingerprint="f" * 64,
            source="alertmanager",
            name="HighCPU",
            severity="critical",
            status="firing",
            labels={"host": "web-01"},
            annotations={},
            starts_at=NOW,
            received_at=NOW,
            incident_id=inc.id,
        )
    )
    db.add(IncidentEvent(incident_id=inc.id, kind="created", payload={}))
    await db.commit()
    await db.refresh(inc)
    return inc


async def test_list_incidents_with_status_filter(client, incident, viewer_headers):
    res = await client.get("/api/v1/incidents", headers=viewer_headers)
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1
    assert res.json()["data"][0]["title"] == "HighCPU on web-01"

    res = await client.get("/api/v1/incidents?status=resolved", headers=viewer_headers)
    assert res.json()["data"] == []


async def test_incident_detail_includes_alerts_and_timeline(
    client, incident, viewer_headers
):
    res = await client.get(f"/api/v1/incidents/{incident.id}", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["alert_count"] == 1
    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["name"] == "HighCPU"
    assert [e["kind"] for e in data["timeline"]] == ["created"]


async def test_editor_can_ack_then_resolve_with_audit(client, incident, editor_headers):
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", headers=editor_headers
    )
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "acknowledged"

    res = await client.post(
        f"/api/v1/incidents/{incident.id}/resolve", headers=editor_headers
    )
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "resolved"

    logs = await client.get(
        f"/api/v1/audit-logs?resource_type=incident&resource_id={incident.id}",
        headers=editor_headers,
    )
    actions = [e["action"] for e in logs.json()["data"]]
    assert "ack" in actions and "resolve" in actions

    detail = await client.get(
        f"/api/v1/incidents/{incident.id}", headers=editor_headers
    )
    kinds = [e["kind"] for e in detail.json()["data"]["timeline"]]
    assert kinds.count("status_changed") == 2


async def test_viewer_cannot_change_status(client, incident, viewer_headers):
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", headers=viewer_headers
    )
    assert res.status_code == 403
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/resolve", headers=viewer_headers
    )
    assert res.status_code == 403


async def test_resolve_is_terminal(client, incident, editor_headers):
    await client.post(
        f"/api/v1/incidents/{incident.id}/resolve", headers=editor_headers
    )
    res = await client.post(
        f"/api/v1/incidents/{incident.id}/ack", headers=editor_headers
    )
    assert res.status_code == 409
