"""Ingestion endpoint: durable ack, static-key auth, provider dispatch.
Correlation is async (worker) — ingest only persists + enqueues."""

from sqlalchemy import select

from app.models.alerting import AlertEvent
from tests.correlation.test_providers import AM_WEBHOOK

INGEST_HEADERS = {"X-Atlas-Ingest-Key": "test-ingest-key"}


async def test_ingest_persists_events_and_acks_202(client, db):
    # AM_WEBHOOK = 1 firing (HighCPU) + 1 resolved (DiskFull). firing -> stored;
    # resolved with no prior match -> no-op (transition semantics, Stage 5).
    res = await client.post("/api/v1/ingest/alertmanager", json=AM_WEBHOOK, headers=INGEST_HEADERS)
    assert res.status_code == 202
    assert res.json()["data"] == {"accepted": 2, "stored": 1, "resolved": 1}

    events = list((await db.execute(select(AlertEvent))).scalars())
    assert len(events) == 1  # only the firing one is a new row
    cpu = events[0]
    assert cpu.name == "HighCPU" and cpu.source == "alertmanager"
    assert cpu.severity == "critical" and cpu.fingerprint
    assert cpu.incident_id is None  # not yet correlated — happens off the queue


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
    res = await client.post("/api/v1/ingest/alertmanager", json=AM_WEBHOOK, headers=INGEST_HEADERS)
    assert res.status_code == 202
