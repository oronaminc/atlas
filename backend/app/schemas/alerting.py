import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.alerting import IncidentStatus

Severity = Literal["critical", "warning", "info"]
AlertStatus = Literal["firing", "resolved"]


class NormalizedAlert(BaseModel):
    """Source-agnostic alert. Providers map raw payloads into this shape;
    the engine never sees provider-specific formats."""

    source: str
    name: str
    severity: Severity = "info"
    status: AlertStatus = "firing"
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    starts_at: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fingerprint: str
    source: str
    name: str
    severity: str
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: datetime
    received_at: datetime
    dedup_count: int
    incident_id: uuid.UUID | None
    # IMP denormalized topology/identity + filter flags
    cmdb_ci: str | None = None
    cmdb_hostname: str | None = None
    cmdb_zone: str | None = None
    client_address: str | None = None
    cmdb_service_l1_code: str | None = None
    cmdb_service_l2_code: str | None = None
    value: float | None = None
    suppressed: bool = False
    correlated: bool = False


class IncidentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    payload: dict
    created_at: datetime


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: IncidentStatus
    severity: str
    group_key: str | None
    first_seen: datetime
    last_seen: datetime
    alert_count: int
    created_at: datetime
    # IMP container fields
    origin: str = "auto"
    cmdb_service_l2_code: str | None = None
    cmdb_service_l1_code: str | None = None
    cmdb_zone: str | None = None
    notify_email: bool = True
    notify_telegram: bool = True
    notify_oncall: bool = False
    grouping_rule_id: uuid.UUID | None = None


class IncidentDetailOut(IncidentOut):
    alerts: list[AlertEventOut] = []
    timeline: list[IncidentEventOut] = []
