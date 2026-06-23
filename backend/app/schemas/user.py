import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.group import GroupRole
from app.models.user import AuthProvider, GlobalRole


class GroupMembershipOut(BaseModel):
    group_id: uuid.UUID
    group_name: str
    role_in_group: GroupRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str
    role: GlobalRole
    auth_provider: AuthProvider
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    groups: list[GroupMembershipOut] = []


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=100)
    password: str | None = Field(default=None, min_length=8)
    role: GlobalRole = GlobalRole.viewer
    auth_provider: AuthProvider = AuthProvider.local


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=100)
    role: GlobalRole | None = None
    is_active: bool | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class MeUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=100)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8)
