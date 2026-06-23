"""Batched Alertmanager webhook: one POST with N alerts in alerts[] is handled
per element — firing -> stored AlertEvent; resolved -> state transition on the
matching stored alert (system auto-resolve), not a new row."""

import pytest
from sqlalchemy import func, select

from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.services.correlation.fingerprint import compute_fingerprint

pytestmark = pytest.mark.asyncio


def _ingest_headers():
    return {"X-Atlas-Ingest-Key": "k"}


async def test_batched_firing_unpacks_each(client, db, monkeypatch):
    import app.api.v1.ingest as ingest

    async def _noop(_ids):
        return None

    monkeypatch.setattr(ingest, "_enqueue", _noop)
    monkeypatch.setattr(ingest.settings, "INGEST_API_KEY", "k")

    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCPU", "severity": "warning", "cmdb_ci": "C1"},
                "annotations": {"value": "83"},
                "startsAt": "2026-06-22T10:00:00Z",
            },
            {
                "status": "firing",
                "labels": {"alertname": "DiskFull", "severity": "info", "cmdb_ci": "C2"},
                "annotations": {},
                "startsAt": "2026-06-22T10:01:00Z",
            },
        ]
    }
    r = await client.post("/api/v1/ingest/alertmanager", json=payload, headers=_ingest_headers())
    assert r.status_code == 202
    assert r.json()["data"] == {"accepted": 2, "stored": 2, "resolved": 0}
    n = (await db.execute(select(func.count()).select_from(AlertEvent))).scalar_one()
    assert n == 2
    cpu = (await db.execute(select(AlertEvent).where(AlertEvent.name == "HighCPU"))).scalar_one()
    assert cpu.value == 83.0  # value parsed at ingest


async def test_batched_mixed_firing_and_resolved(client, db, monkeypatch):
    import app.api.v1.ingest as ingest

    async def _noop(_ids):
        return None

    monkeypatch.setattr(ingest, "_enqueue", _noop)
    monkeypatch.setattr(ingest.settings, "INGEST_API_KEY", "k")

    # pre-existing firing alert that the batch will resolve
    labels = {"cmdb_ci": "C9"}
    db.add(
        AlertEvent(
            fingerprint=compute_fingerprint("alertmanager", "OldAlert", labels),
            source="alertmanager",
            name="OldAlert",
            severity="critical",
            status="firing",
            labels=labels,
            annotations={},
            starts_at=utcnow(),
            received_at=utcnow(),
        )
    )
    await db.commit()

    payload = {
        "alerts": [
            {  # new firing -> stored
                "status": "firing",
                "labels": {"alertname": "NewAlert", "severity": "warning", "cmdb_ci": "C3"},
                "annotations": {},
                "startsAt": "2026-06-22T10:00:00Z",
            },
            {  # resolved for the pre-existing one -> transition, no new row
                "status": "resolved",
                "labels": {"alertname": "OldAlert", "cmdb_ci": "C9"},
                "annotations": {},
                "startsAt": "2026-06-22T09:00:00Z",
            },
        ]
    }
    r = await client.post("/api/v1/ingest/alertmanager", json=payload, headers=_ingest_headers())
    assert r.json()["data"] == {"accepted": 2, "stored": 1, "resolved": 1}

    # 2 rows total: OldAlert (now resolved) + NewAlert (firing). No new row for the resolved.
    rows = {e.name: e for e in (await db.execute(select(AlertEvent))).scalars()}
    assert set(rows) == {"OldAlert", "NewAlert"}
    assert rows["OldAlert"].status == "resolved"  # system-resolved per element
    assert rows["NewAlert"].status == "firing"
