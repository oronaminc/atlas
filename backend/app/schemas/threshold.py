import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class RuleCatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    alertname: str
    comparator: str | None
    unit: str | None
    value_query: str | None


class RuleCatalogUpdate(BaseModel):
    comparator: Literal[">", "<"] | None = None
    unit: str | None = None
    value_query: str | None = None


class ThresholdOverrideCreate(BaseModel):
    alertname: str
    tier: Literal["server", "group"]
    target_cmdb_ci: str | None = None
    target_group_id: uuid.UUID | None = None
    value: float

    @model_validator(mode="after")
    def _check(self) -> "ThresholdOverrideCreate":
        if self.tier == "server" and not self.target_cmdb_ci:
            raise ValueError("server override requires target_cmdb_ci")
        if self.tier == "group" and not self.target_group_id:
            raise ValueError("group override requires target_group_id")
        return self


class ThresholdOverrideUpdate(BaseModel):
    value: float


class ThresholdOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alertname: str
    tier: str
    target_cmdb_ci: str | None
    target_group_id: uuid.UUID | None
    value: float
