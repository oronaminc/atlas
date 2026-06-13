import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MASKED = "********"


class LLMConfigOut(BaseModel):
    enabled: bool
    base_url: str
    api_key: str | None  # masked, never the stored value
    model: str
    max_prompt_chars: int
    max_completion_tokens: int
    daily_quota: int
    auto_analyze: bool
    redact_external_strict: bool


class LLMConfigUpdate(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = None  # MASKED sentinel = keep current; "" = clear
    model: str | None = Field(default=None, max_length=200)
    max_prompt_chars: int | None = Field(default=None, ge=500, le=100000)
    max_completion_tokens: int | None = Field(default=None, ge=16, le=8192)
    daily_quota: int | None = Field(default=None, ge=0)
    auto_analyze: bool | None = None
    redact_external_strict: bool | None = None


class IncidentAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: uuid.UUID
    status: str
    summary: str | None
    root_cause: str | None
    model: str | None
    tokens_used: int
    error: str | None
    completed_at: datetime | None
