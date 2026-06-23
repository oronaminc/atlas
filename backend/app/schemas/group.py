import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.group import GroupRole


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    labels: list[str] = []
    created_at: datetime
    member_count: int = 0


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    labels: list[str] | None = None


class GroupMemberAdd(BaseModel):
    user_id: uuid.UUID
    role_in_group: GroupRole = GroupRole.member


class GroupMemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    role_in_group: GroupRole
