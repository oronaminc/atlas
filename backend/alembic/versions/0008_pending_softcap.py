"""observability: notification_settings.pending_softcap

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-13

Per-service pending-queue alarm threshold (Phase 5). 0001 pre-creates current
columns on fresh DBs, so the add is inspector-guarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("notification_settings")}
    if "pending_softcap" not in cols:
        op.add_column(
            "notification_settings",
            sa.Column("pending_softcap", sa.Integer(), nullable=False, server_default="50000"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("notification_settings")}
    if "pending_softcap" in cols:
        op.drop_column("notification_settings", "pending_softcap")
