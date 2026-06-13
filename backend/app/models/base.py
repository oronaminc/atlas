import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

# JSONB on PostgreSQL, plain JSON elsewhere (tests run on SQLite).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class AwareDateTime(TypeDecorator):
    """Always returns tz-aware (UTC) datetimes. SQLite drops tzinfo on the
    round-trip; asyncpg already returns aware values unchanged."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TenantScoped:
    """Row-level tenancy mixin. tenant_id is nullable by design:
    NULL = legacy/system rows, visible ONLY to HQ users (tenant_scope None).
    The session-level choke point in core/tenancy.py auto-filters every
    SELECT on these models and stamps tenant_id on flush when a scope is
    set — endpoints never apply tenant filters themselves."""

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)


class TimestampedBase(Base):
    """Common columns shared by every table: uuid pk + audit timestamps/actors."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=utcnow,
        onupdate=utcnow,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
