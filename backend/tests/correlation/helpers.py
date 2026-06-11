from datetime import UTC, datetime

from app.schemas.alerting import NormalizedAlert


def alert(
    name: str = "HighCPU",
    source: str = "alertmanager",
    severity: str = "critical",
    status: str = "firing",
    labels: dict | None = None,
    starts_at: datetime | None = None,
) -> NormalizedAlert:
    return NormalizedAlert(
        source=source,
        name=name,
        severity=severity,
        status=status,
        labels=labels if labels is not None else {"host": "web-01"},
        annotations={"summary": f"{name} fired"},
        starts_at=starts_at or datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC),
    )
