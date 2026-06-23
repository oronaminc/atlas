import uuid

from pydantic import BaseModel, ConfigDict, model_validator


class ThresholdOverrideCreate(BaseModel):
    alertname: str
    # label-based target: a specific server (cmdb_ci) OR a label (key,value).
    target_cmdb_ci: str | None = None
    target_label_key: str | None = None
    target_label_value: str | None = None
    value: float

    @model_validator(mode="after")
    def _check(self) -> "ThresholdOverrideCreate":
        if self.target_cmdb_ci:
            return self
        if self.target_label_key and self.target_label_value:
            return self
        raise ValueError(
            "override requires target_cmdb_ci or (target_label_key, target_label_value)"
        )


class ThresholdOverrideUpdate(BaseModel):
    value: float


class ThresholdOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alertname: str
    target_cmdb_ci: str | None
    target_label_key: str | None
    target_label_value: str | None
    value: float
