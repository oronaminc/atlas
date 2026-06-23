"""Read-only schemas for the Mimir read-cache (rules + silences)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PulledRuleOut(BaseModel):
    """One alerting rule from the Mimir rules cache: what it is, how it's
    collected (health/state/last eval), its read value, and the atlas base
    threshold (read from the rule's own labels/annotations — never PromQL)."""

    model_config = ConfigDict(from_attributes=True)

    alertname: str
    expr: str
    for_seconds: int | None = None
    severity: str | None = None
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    namespace: str = ""
    group_name: str = ""
    health: str | None = None
    state: str | None = None
    last_error: str | None = None
    last_evaluation: datetime | None = None
    value: float | None = None
    base_threshold: float | None = None
    comparator: str | None = None
    synced_at: datetime | None = None


class SilenceMatcher(BaseModel):
    name: str
    value: str
    isRegex: bool = False
    isEqual: bool = True


class SilenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    silence_id: str
    matchers: list[dict] = []
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    comment: str | None = None
    created_by_label: str | None = None
    state: str | None = None


class SilenceCreate(BaseModel):
    """The user picks WHAT to silence (a service or a server) + a window +
    description — never a query/matcher. atlas builds the AM label matcher."""

    target_kind: Literal["service", "server"]
    target_value: str  # the cmdb_service_l2_code (service) or cmdb_ci (server)
    starts_at: datetime
    ends_at: datetime
    comment: str = ""
