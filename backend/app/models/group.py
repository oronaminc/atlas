import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TenantScoped, TimestampedBase


class GroupRole(enum.StrEnum):
    member = "member"
    manager = "manager"


class Group(TenantScoped, TimestampedBase):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

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


from app.models.user import User  # noqa: E402,F401
