import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    labels: dict[str, str]
    description: str | None
    owner_group_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    labels: dict[str, str] = {}
    description: str | None = None
    owner_group_id: uuid.UUID | None = None


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    labels: dict[str, str] | None = None
    description: str | None = None
    owner_group_id: uuid.UUID | None = None
