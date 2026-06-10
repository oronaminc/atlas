import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.rule import Datasource, ScopeType, Severity

DURATION_RE = re.compile(r"^\d+(ms|s|m|h|d|w|y)$")


def validate_duration(v: str) -> str:
    if not DURATION_RE.match(v):
        raise ValueError("duration must look like 30s, 5m, 1h ...")
    return v


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    scope_type: ScopeType
    scope_ref_id: uuid.UUID | None
    expr: str
    for_duration: str
    severity: Severity
    labels: dict[str, str]
    annotations: dict[str, str]
    enabled: bool
    datasource: Datasource
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scope_type: ScopeType
    scope_ref_id: uuid.UUID | None = None
    expr: str = Field(min_length=1)
    for_duration: str = "5m"
    severity: Severity
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    enabled: bool = True
    datasource: Datasource = Datasource.metrics

    _duration = field_validator("for_duration")(validate_duration)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    scope_type: ScopeType | None = None
    scope_ref_id: uuid.UUID | None = None
    expr: str | None = Field(default=None, min_length=1)
    for_duration: str | None = None
    severity: Severity | None = None
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None
    enabled: bool | None = None
    datasource: Datasource | None = None

    @field_validator("for_duration")
    @classmethod
    def _duration(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_duration(v)


class RuleValidateResult(BaseModel):
    valid: bool
    errors: list[str] = []


class RuleTestResult(BaseModel):
    success: bool
    result: list[dict] = []
    error: str | None = None


class EmergencyApplyRequest(BaseModel):
    rule_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)


class RuleGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    namespace: str
    interval: str
    tenant: str
    created_at: datetime
    rule_count: int = 0
    rules: list[AlertRuleOut] = []


class RuleGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    namespace: str = Field(min_length=1, max_length=255)
    interval: str = "1m"
    rule_ids: list[uuid.UUID] = []

    _interval = field_validator("interval")(validate_duration)


class RuleGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    namespace: str | None = Field(default=None, min_length=1, max_length=255)
    interval: str | None = None
    rule_ids: list[uuid.UUID] | None = None

    @field_validator("interval")
    @classmethod
    def _interval(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_duration(v)
