"""Provider boundary: each alert source implements parse(raw) -> NormalizedAlert[].
Adding Datadog/Sentry later = a new module + registry entry; the engine is untouched."""

from typing import Any, Protocol

from app.schemas.alerting import NormalizedAlert


class AlertProvider(Protocol):
    name: str

    def parse(self, payload: dict[str, Any]) -> list[NormalizedAlert]: ...
