import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

MASKED = "********"


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID | None = None  # NULL on a dissolved-incident orphan
    channel: str
    recipient_user_id: uuid.UUID | None = None
    recipient_address: str
    group_id: uuid.UUID | None
    status: str
    attempts: int
    retry_at: datetime | None
    sent_at: datetime | None
    last_error: str | None
    created_at: datetime


class GroupChannelOut(BaseModel):
    """A group's channel destination. Secrets (bot token / webhook) are MASKED."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel: str
    enabled: bool
    chat_id: str | None = None
    email: str | None = None
    bot_token: str | None = None  # MASKED when set
    webhook_url: str | None = None  # MASKED when set
    oncall_token: str | None = None  # MASKED when set


class GroupChannelCreate(BaseModel):
    channel: Literal["telegram", "email", "oncall"]
    enabled: bool = True
    chat_id: str | None = None
    email: str | None = None
    bot_token: str | None = None  # telegram
    webhook_url: str | None = None  # oncall
    oncall_token: str | None = None  # oncall bearer (optional)

    @model_validator(mode="after")
    def _check(self) -> "GroupChannelCreate":
        if self.channel == "telegram" and not (self.bot_token and self.chat_id):
            raise ValueError("telegram channel requires bot_token + chat_id")
        if self.channel == "email" and not self.email:
            raise ValueError("email channel requires email")
        if self.channel == "oncall" and not self.webhook_url:
            raise ValueError("oncall channel requires webhook_url")
        return self


class RecipientOut(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    telegram_chat_id: str | None
    groups: list[str]


class NotifyRequest(BaseModel):
    group_id: uuid.UUID
