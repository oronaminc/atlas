import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JsonType, TimestampedBase


class GroupRole(enum.StrEnum):
    member = "member"
    manager = "manager"


class Group(TimestampedBase):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # descriptive label tags (selected from the Mimir label API). METADATA ONLY —
    # NOT a routing/visibility key (that stays cmdb_service_l2_code via group_service_codes).
    labels: Mapped[list[str]] = mapped_column(JsonType, default=list)

    memberships: Mapped[list["UserGroup"]] = relationship(
        back_populates="group", lazy="selectin", cascade="all, delete-orphan"
    )


class UserGroup(TimestampedBase):
    __tablename__ = "user_group"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_group"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    role_in_group: Mapped[GroupRole] = mapped_column(
        Enum(GroupRole, name="group_role"), default=GroupRole.member
    )

    user: Mapped["User"] = relationship(back_populates="memberships", lazy="joined")  # noqa: F821
    group: Mapped[Group] = relationship(back_populates="memberships", lazy="joined")


class GroupServiceCode(TimestampedBase):
    """IMP redesign §6: a user group maps to many cmdb_service_l2_codes (1:N).
    This is the ONE managed list — it governs visibility (which alerts/incidents
    a group's members see) and notification routing (an incident's l2_code →
    the groups mapped to it → their members). Not tenant-scoped."""

    __tablename__ = "group_service_codes"
    __table_args__ = (
        UniqueConstraint("group_id", "cmdb_service_l2_code", name="uq_group_service_code"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    cmdb_service_l2_code: Mapped[str] = mapped_column(String(255), index=True)


from app.models.user import User  # noqa: E402,F401
