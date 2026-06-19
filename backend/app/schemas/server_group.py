import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

CMDB_CI_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


class ServerGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class ServerGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ServerGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None
    member_count: int = 0


class BulkMembersRequest(BaseModel):
    """cmdb_ci list to (re)assign into the group. Caller may pass raw newline/CSV
    text split client-side; here it's a clean list. Dedup + validate server-side."""

    cmdb_cis: list[str] = Field(min_length=1)

    @field_validator("cmdb_cis")
    @classmethod
    def _strip(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v]


class BulkMembersResult(BaseModel):
    added: int
    reassigned: int
    already_in_group: int
    rejected: list[str]


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    cmdb_ci: str | None
    server_group_id: uuid.UUID | None
