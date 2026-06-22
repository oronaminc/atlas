"""Read-only schema for rules pulled from the Mimir Ruler (IMP: pull-only)."""

from pydantic import BaseModel, Field


class PulledRuleOut(BaseModel):
    """One alerting rule as read from the Ruler config API."""

    alertname: str
    expr: str
    # `for` is a Python keyword; expose it as for_ internally, serialize as "for"
    for_: str | None = Field(default=None, alias="for")
    severity: str | None = None
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    namespace: str = ""
    group: str = ""

    model_config = {"populate_by_name": True}
