import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    tenant_id: uuid.UUID | None = None
    group_key: str | None
    first_seen: datetime
    last_seen: datetime
    alert_count: int
    created_at: datetime


class IncidentDetailOut(IncidentOut):
    alerts: list[AlertEventOut] = []
    timeline: list[IncidentEventOut] = []


class CorrelationConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dedup_window_seconds: int
    correlation_window_seconds: int
    group_attrs: list[str]


class CorrelationConfigUpdate(BaseModel):
    dedup_window_seconds: int | None = Field(default=None, ge=1)
    correlation_window_seconds: int | None = Field(default=None, ge=1)
    group_attrs: list[str] | None = Field(default=None, min_length=1)
