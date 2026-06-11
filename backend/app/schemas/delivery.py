import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MASKED = "********"


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    channel: str
    recipient_user_id: uuid.UUID
    recipient_address: str
    group_id: uuid.UUID | None
    status: str
    attempts: int
    retry_at: datetime | None
    sent_at: datetime | None
    last_error: str | None
    created_at: datetime


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID
    min_severity: str
    channels: list[str]
    enabled: bool
    created_at: datetime


class RouteCreate(BaseModel):
    group_id: uuid.UUID
    min_severity: str = Field(default="warning", pattern="^(critical|warning|info)$")
    channels: list[str] = Field(default=["telegram"], min_length=1)
    enabled: bool = True


class RouteUpdate(BaseModel):
    min_severity: str | None = Field(default=None, pattern="^(critical|warning|info)$")
    channels: list[str] | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class NotificationSettingsOut(BaseModel):
    telegram_bot_token: str | None  # masked, never the stored value
    telegram_rate_per_second: int
    quota_group_per_hour: int
    quota_global_per_day: int


class NotificationSettingsUpdate(BaseModel):
    telegram_bot_token: str | None = None  # MASKED sentinel = keep current
    telegram_rate_per_second: int | None = Field(default=None, ge=1)
    quota_group_per_hour: int | None = Field(default=None, ge=1)
    quota_global_per_day: int | None = Field(default=None, ge=1)


class RecipientOut(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    telegram_chat_id: str | None
    groups: list[str]


class NotifyRequest(BaseModel):
    group_id: uuid.UUID
