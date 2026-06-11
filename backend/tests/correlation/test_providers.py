"""Provider boundary: raw source payload -> list[NormalizedAlert].
Alertmanager is provider #1; adding Datadog/Sentry later must not touch the engine."""

import pytest

from app.providers.alertmanager import AlertmanagerProvider
from app.providers.registry import get_provider

AM_WEBHOOK = {
    "version": "4",
    "status": "firing",
    "receiver": "atlas",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "HighCPU", "severity": "critical", "host": "web-01"},
            "annotations": {"summary": "CPU > 90%"},
            "startsAt": "2026-06-10T00:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
        },
        {
            "status": "resolved",
            "labels": {"alertname": "DiskFull", "severity": "warning", "host": "db-01"},
            "annotations": {},
            "startsAt": "2026-06-09T23:00:00Z",
            "endsAt": "2026-06-10T00:30:00Z",
        },
    ],
}


def test_alertmanager_provider_normalizes_webhook():
    alerts = AlertmanagerProvider().parse(AM_WEBHOOK)
    assert len(alerts) == 2

    first = alerts[0]
    assert first.source == "alertmanager"
    assert first.name == "HighCPU"
    assert first.severity == "critical"
    assert first.status == "firing"
    assert first.labels["host"] == "web-01"
    # alertname/severity are lifted out; remaining labels keep identity attrs
    assert first.annotations == {"summary": "CPU > 90%"}
    assert first.starts_at.isoformat().startswith("2026-06-10T00:00:00")

    second = alerts[1]
    assert second.status == "resolved"
    assert second.severity == "warning"


def test_alertmanager_provider_defaults_missing_severity_to_info():
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "NoSev"},
                "annotations": {},
                "startsAt": "2026-06-10T00:00:00Z",
            }
        ]
    }
    alerts = AlertmanagerProvider().parse(payload)
    assert alerts[0].severity == "info"


def test_registry_resolves_known_provider():
    assert get_provider("alertmanager").name == "alertmanager"


def test_registry_rejects_unknown_provider():
    with pytest.raises(KeyError):
        get_provider("nagios")
