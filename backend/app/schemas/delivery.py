import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MASKED = "********"


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    channel: str
    # NULL for OnCall team-webhook rows (one row per incident, no user recipient)
    recipient_user_id: uuid.UUID | None = None
    recipient_address: str
    group_id: uuid.UUID | None
    status: str
    attempts: int
    retry_at: datetime | None
    sent_at: datetime | None
    last_error: str | None
    created_at: datetime


class NotificationSettingsOut(BaseModel):
    telegram_bot_token: str | None  # masked, never the stored value
    telegram_rate_per_second: int
    quota_group_per_hour: int
    quota_global_per_day: int
    pending_softcap: int


class NotificationSettingsUpdate(BaseModel):
    telegram_bot_token: str | None = None  # MASKED sentinel = keep current
    telegram_rate_per_second: int | None = Field(default=None, ge=1)
    quota_group_per_hour: int | None = Field(default=None, ge=1)
    quota_global_per_day: int | None = Field(default=None, ge=1)
    pending_softcap: int | None = Field(default=None, ge=1)


class RecipientOut(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    telegram_chat_id: str | None
    groups: list[str]


class NotifyRequest(BaseModel):
    group_id: uuid.UUID
