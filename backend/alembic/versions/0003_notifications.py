"""notification delivery: outbox, routes, settings; HA claim columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonType = sa.JSON().with_variant(JSONB(), "postgresql")

COMMON = lambda: [  # noqa: E731  (shared audit columns per spec)
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("created_by", sa.Uuid(), nullable=True),
    sa.Column("updated_by", sa.Uuid(), nullable=True),
]


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    # Fresh installs create these via 0001's metadata-based bootstrap; only
    # databases migrated from older revisions actually need the ALTER.
    inspector = sa.inspect(op.get_bind())
    if column.name not in {c["name"] for c in inspector.get_columns(table)}:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing(
        "users", sa.Column("telegram_chat_id", sa.String(64), nullable=True)
    )
    _add_column_if_missing(
        "incidents", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column_if_missing(
        "alert_events",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "alert_events", sa.Column("claimed_by", sa.String(100), nullable=True)
    )

    op.create_table(
        "notification_settings",
        *COMMON(),
        sa.Column("telegram_bot_token", sa.Text(), nullable=True),
        sa.Column("telegram_rate_per_second", sa.Integer(), nullable=False),
        sa.Column("quota_group_per_hour", sa.Integer(), nullable=False),
        sa.Column("quota_global_per_day", sa.Integer(), nullable=False),
    )

    op.create_table(
        "notification_routes",
        *COMMON(),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("min_severity", sa.String(20), nullable=False),
        sa.Column("channels", JsonType, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("group_id", name="uq_notification_route_group"),
    )

    op.create_table(
        "notifications",
        *COMMON(),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column(
            "recipient_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_address", sa.String(255), nullable=False),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "incident_id", "channel", "recipient_user_id", name="uq_notification_target"
        ),
    )
    op.create_index("ix_notifications_incident_id", "notifications", ["incident_id"])
    op.create_index("ix_notifications_group_id", "notifications", ["group_id"])
    op.create_index(
        "ix_notifications_status_retry", "notifications", ["status", "retry_at"]
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("notification_routes")
    op.drop_table("notification_settings")
    op.drop_column("alert_events", "claimed_by")
    op.drop_column("alert_events", "claimed_at")
    op.drop_column("incidents", "notified_at")
    op.drop_column("users", "telegram_chat_id")
