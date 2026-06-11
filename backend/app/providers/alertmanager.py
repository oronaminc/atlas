"""Provider #1: Prometheus/Mimir Alertmanager webhook (version 4 payload)."""

from datetime import UTC, datetime
from typing import Any

from app.schemas.alerting import NormalizedAlert

_VALID_SEVERITIES = {"critical", "warning", "info"}


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AlertmanagerProvider:
    name = "alertmanager"

    def parse(self, payload: dict[str, Any]) -> list[NormalizedAlert]:
        alerts: list[NormalizedAlert] = []
        for raw in payload.get("alerts", []):
            labels = dict(raw.get("labels") or {})
            name = labels.pop("alertname", "unknown")
            severity = labels.pop("severity", "info")
            if severity not in _VALID_SEVERITIES:
                severity = "info"
            status = raw.get("status", "firing")
            alerts.append(
                NormalizedAlert(
                    source=self.name,
                    name=name,
                    severity=severity,  # type: ignore[arg-type]
                    status="resolved" if status == "resolved" else "firing",
                    labels=labels,
                    annotations=dict(raw.get("annotations") or {}),
                    starts_at=_parse_ts(raw.get("startsAt")),
                )
            )
        return alerts
