import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    is_active: bool
    mimir_orgs: list[str] = []
    created_at: datetime


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    mimir_orgs: list[str] = Field(default_factory=list)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    mimir_orgs: list[str] | None = None
