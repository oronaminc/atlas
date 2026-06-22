"""IMP stage 2: ingest denormalizes the canonical cmdb_* labels onto AlertEvent
columns, and ingest itself never creates an incident (incident formation lives
only in the correlation worker). Missing labels -> NULL columns."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models.alerting import AlertEvent, Incident
from app.providers.alertmanager import AlertmanagerProvider
from app.services.correlation.engine import build_event

CANONICAL = {
    "job": "integrations/unix",
    "mode": "idle",
    "alertname": "HostHighCpuLoad",
    "severity": "critical",
    "cmdb_ci": "CS20260305_1733050772",
    "instance": "idv-giantd-builder-001",
    "cmdb_hostname": "idv-giantd-builder-001",
    "client_address": "192.168.81.250",
    "cmdb_service_l1": "SPACE (VM)",
    "cmdb_service_l2": "[SPACE]GIANT 개발",
    "cmdb_environment": "개발/테스트",
    "cmdb_service_l1_code": "ssm20240822_00001",
    "cmdb_service_l2_code": "sub20251126_1040230842",
    "cmdb_zone": "둔산_10F_D1",
}


def _payload(labels):
    return {
        "alerts": [
            {
                "labels": labels,
                "annotations": {},
                "status": "firing",
                "startsAt": "2026-06-20T00:00:00Z",
            }
        ]
    }


def test_build_event_denorm_extraction():
    [alert] = AlertmanagerProvider().parse(_payload(CANONICAL))
    ev = build_event(alert, received_at=datetime.now(UTC))
    assert ev.cmdb_ci == "CS20260305_1733050772"
    assert ev.cmdb_hostname == "idv-giantd-builder-001"
    assert ev.cmdb_zone == "둔산_10F_D1"
    assert ev.client_address == "192.168.81.250"
    assert ev.cmdb_service_l1_code == "ssm20240822_00001"
    assert ev.cmdb_service_l2_code == "sub20251126_1040230842"
    # raw labels still fully preserved (alertname/severity popped by provider)
    assert ev.labels["cmdb_service_l2"] == "[SPACE]GIANT 개발"
    assert "alertname" not in ev.labels


def test_build_event_missing_labels_null():
    [alert] = AlertmanagerProvider().parse(
        _payload({"alertname": "X", "severity": "warning", "cmdb_ci": "CS_ONLY"})
    )
    ev = build_event(alert, received_at=datetime.now(UTC))
    assert ev.cmdb_ci == "CS_ONLY"
    assert ev.cmdb_zone is None
    assert ev.client_address is None
    assert ev.cmdb_service_l2_code is None


async def test_ingest_stores_denormed_alert_and_no_incident(client, db):
    res = await client.post(
        "/api/v1/ingest/alertmanager",
        json=_payload(CANONICAL),
        headers={"X-Atlas-Ingest-Key": "test-ingest-key"},
    )
    assert res.status_code == 202
    assert res.json()["data"]["accepted"] == 1

    ev = (await db.execute(select(AlertEvent))).scalars().one()
    assert ev.cmdb_service_l2_code == "sub20251126_1040230842"
    assert ev.cmdb_zone == "둔산_10F_D1"
    assert ev.incident_id is None  # not attached at ingest

    # the core invariant: ingest creates ZERO incidents
    n_incidents = (await db.execute(select(func.count()).select_from(Incident))).scalar_one()
    assert n_incidents == 0
