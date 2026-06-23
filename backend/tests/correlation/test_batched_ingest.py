"""Batched Alertmanager webhook: one POST with N alerts in alerts[] is unpacked
into N individual AlertEvents (mixed firing/resolved honored per element)."""

from sqlalchemy import func, select

from app.models.alerting import AlertEvent

PAYLOAD = {
    "version": "4",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighCPU", "severity": "warning", "cmdb_ci": "CI-1"},
            "annotations": {"value": "83"},
            "startsAt": "2026-06-22T10:00:00Z",
        },
        {
            "status": "resolved",
            "labels": {"alertname": "HighMem", "severity": "critical", "cmdb_ci": "CI-2"},
            "annotations": {"value": "12"},
            "startsAt": "2026-06-22T10:01:00Z",
        },
        {
            "status": "firing",
            "labels": {"alertname": "DiskFull", "severity": "info", "cmdb_ci": "CI-3"},
            "annotations": {},
            "startsAt": "2026-06-22T10:02:00Z",
        },
    ],
}


async def test_batched_webhook_unpacks_each_alert(client, db, monkeypatch):
    import app.api.v1.ingest as ingest

    async def _noop(_ids):
        return None

    monkeypatch.setattr(ingest, "_enqueue", _noop)
    monkeypatch.setattr(ingest.settings, "INGEST_API_KEY", "k")

    r = await client.post(
        "/api/v1/ingest/alertmanager", json=PAYLOAD, headers={"X-Atlas-Ingest-Key": "k"}
    )
    assert r.status_code == 202
    assert r.json()["data"]["accepted"] == 3

    n = (await db.execute(select(func.count()).select_from(AlertEvent))).scalar_one()
    assert n == 3
    by_name = {e.name: e for e in (await db.execute(select(AlertEvent))).scalars()}
    assert set(by_name) == {"HighCPU", "HighMem", "DiskFull"}
    # status honored per element
    assert by_name["HighMem"].status == "resolved"
    assert by_name["HighCPU"].status == "firing"
    # value parsed from annotations at ingest
    assert by_name["HighCPU"].value == 83.0
