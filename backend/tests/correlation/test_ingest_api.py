"""Ingestion endpoint: durable ack, static-key auth, provider dispatch.
Correlation is async (worker) — ingest only persists + enqueues."""

from sqlalchemy import select

from app.models.alerting import AlertEvent
from tests.correlation.test_providers import AM_WEBHOOK

INGEST_HEADERS = {"X-Atlas-Ingest-Key": "test-ingest-key"}


async def test_ingest_persists_events_and_acks_202(client, db):
    res = await client.post(
        "/api/v1/ingest/alertmanager", json=AM_WEBHOOK, headers=INGEST_HEADERS
    )
    assert res.status_code == 202
    assert res.json()["data"]["accepted"] == 2

    events = list((await db.execute(select(AlertEvent))).scalars())
    assert len(events) == 2
    by_name = {e.name: e for e in events}
    assert by_name["HighCPU"].source == "alertmanager"
    assert by_name["HighCPU"].severity == "critical"
    assert by_name["HighCPU"].fingerprint
    # not yet correlated — that happens off the queue
    assert all(e.incident_id is None for e in events)


async def test_ingest_requires_valid_key(client):
    res = await client.post("/api/v1/ingest/alertmanager", json=AM_WEBHOOK)
    assert res.status_code == 401

    res = await client.post(
        "/api/v1/ingest/alertmanager",
        json=AM_WEBHOOK,
        headers={"X-Atlas-Ingest-Key": "wrong"},
    )
    assert res.status_code == 401


async def test_ingest_unknown_provider_404(client):
    res = await client.post("/api/v1/ingest/nagios", json={}, headers=INGEST_HEADERS)
    assert res.status_code == 404


async def test_ingest_does_not_require_user_jwt(client):
    """Machine endpoint: key only, no bearer token."""
    res = await client.post(
        "/api/v1/ingest/alertmanager", json=AM_WEBHOOK, headers=INGEST_HEADERS
    )
    assert res.status_code == 202
