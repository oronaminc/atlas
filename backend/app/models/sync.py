import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class SyncTarget(enum.StrEnum):
    ruler = "ruler"
    alertmanager = "alertmanager"


class SyncStatus(enum.StrEnum):
    ok = "ok"
    pending = "pending"
    failed = "failed"


class SyncState(TimestampedBase):
    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("target", name="uq_sync_target"),)

    target: Mapped[SyncTarget] = mapped_column(Enum(SyncTarget, name="sync_target"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), default=SyncStatus.pending
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
