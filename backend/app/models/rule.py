import enum
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JsonType, TimestampedBase


class ScopeType(enum.StrEnum):
    global_ = "global"
    server = "server"
    user = "user"
    group = "group"


class Severity(enum.StrEnum):
    critical = "critical"
    warning = "warning"
    info = "info"


class Datasource(enum.StrEnum):
    metrics = "metrics"
    logs = "logs"


class AlertRule(TimestampedBase):
    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_type: Mapped[ScopeType] = mapped_column(
        Enum(
            ScopeType,
            name="scope_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        index=True,
    )
    scope_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    expr: Mapped[str] = mapped_column(Text)
    for_duration: Mapped[str] = mapped_column(String(20), default="5m")
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), index=True)
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    datasource: Mapped[Datasource] = mapped_column(
        Enum(Datasource, name="datasource"), default=Datasource.metrics
    )

    group_links: Mapped[list["RuleGroupRule"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class RuleGroup(TimestampedBase):
    __tablename__ = "rule_groups"
    __table_args__ = (UniqueConstraint("namespace", "name", name="uq_rule_group_ns_name"),)

    name: Mapped[str] = mapped_column(String(255), index=True)
    namespace: Mapped[str] = mapped_column(String(255), index=True)
    interval: Mapped[str] = mapped_column(String(20), default="1m")
    tenant: Mapped[str] = mapped_column(String(100), default="system")

    rule_links: Mapped[list["RuleGroupRule"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="RuleGroupRule.order",
        lazy="selectin",
    )


class RuleGroupRule(TimestampedBase):
    __tablename__ = "rule_group_rules"
    __table_args__ = (
        UniqueConstraint("rule_group_id", "alert_rule_id", name="uq_rule_group_rule"),
    )

    rule_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rule_groups.id", ondelete="CASCADE"), index=True
    )
    alert_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column(Integer, default=0)

    group: Mapped[RuleGroup] = relationship(back_populates="rule_links")
    rule: Mapped[AlertRule] = relationship(back_populates="group_links", lazy="joined")
