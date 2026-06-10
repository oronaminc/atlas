import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import ReceiverType


class ReceiverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: ReceiverType
    # Secrets are masked when returned to clients.
    config: dict
    created_at: datetime


class ReceiverCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: ReceiverType
    config: dict = {}


class ReceiverUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict | None = None


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    matcher: dict
    receiver_id: uuid.UUID
    group_by: list[str]
    repeat_interval: str
    created_at: datetime


class PolicyCreate(BaseModel):
    matcher: dict = {}
    receiver_id: uuid.UUID
    group_by: list[str] = []
    repeat_interval: str = "4h"


class PolicyUpdate(BaseModel):
    matcher: dict | None = None
    receiver_id: uuid.UUID | None = None
    group_by: list[str] | None = None
    repeat_interval: str | None = None


class SilenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    matchers: dict
    starts_at: datetime
    ends_at: datetime
    comment: str
    created_by: uuid.UUID | None
    created_at: datetime


class SilenceCreate(BaseModel):
    matchers: dict = {}
    starts_at: datetime
    ends_at: datetime
    comment: str = ""
