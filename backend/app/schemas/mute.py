import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class MuteCreate(BaseModel):
    target_type: Literal["server", "group", "all"]
    target_cmdb_ci: str | None = None
    target_group_id: uuid.UUID | None = None
    alertname: str | None = None  # NULL = mute ALL rules for the target
    reason: str | None = None

    @model_validator(mode="after")
    def _check_target(self) -> "MuteCreate":
        if self.target_type == "server" and not self.target_cmdb_ci:
            raise ValueError("server mute requires target_cmdb_ci")
        if self.target_type == "group" and not self.target_group_id:
            raise ValueError("group mute requires target_group_id")
        if self.target_type == "all" and (self.target_cmdb_ci or self.target_group_id):
            raise ValueError("'all' mute must not set a target")
        if self.target_type == "all" and self.alertname is None:
            raise ValueError("'all'-target mute requires an alertname (would mute everything)")
        return self


class MuteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    target_type: str
    target_cmdb_ci: str | None
    target_group_id: uuid.UUID | None
    alertname: str | None
    enabled: bool
    reason: str | None
