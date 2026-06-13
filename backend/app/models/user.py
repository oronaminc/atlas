import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedBase


class AuthProvider(enum.StrEnum):
    local = "local"
    oidc = "oidc"


class GlobalRole(enum.StrEnum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class User(TimestampedBase):
    __tablename__ = "users"

    # NULL = HQ user (sees all tenants); set = locked to that tenant.
    # No FK: 0001's metadata bootstrap creates users before tenants exists;
    # tenants are soft-deactivated, never hard-deleted.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, name="auth_provider"), default=AuthProvider.local
    )
    oidc_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[GlobalRole] = mapped_column(
        Enum(GlobalRole, name="global_role"), default=GlobalRole.viewer
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["UserGroup"]] = relationship(  # noqa: F821
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )


from app.models.group import UserGroup  # noqa: E402,F401  (resolve forward ref)
