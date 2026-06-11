"""correlation engine: alert_events, incidents, incident_events, correlation_config

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
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


def upgrade() -> None:
    op.create_table(
        "incidents",
        *COMMON(),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "acknowledged", "resolved", name="incident_status"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_group_key_last_seen", "incidents", ["group_key", "last_seen"])

    op.create_table(
        "alert_events",
        *COMMON(),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("labels", JsonType, nullable=False),
        sa.Column("annotations", JsonType, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedup_count", sa.Integer(), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_alert_events_fingerprint", "alert_events", ["fingerprint"])
    op.create_index("ix_alert_events_source", "alert_events", ["source"])
    op.create_index("ix_alert_events_received_at", "alert_events", ["received_at"])
    op.create_index("ix_alert_events_incident_id", "alert_events", ["incident_id"])
    op.create_index("ix_alert_events_fp_received", "alert_events", ["fingerprint", "received_at"])

    op.create_table(
        "incident_events",
        *COMMON(),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("payload", JsonType, nullable=False),
    )
    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])

    op.create_table(
        "correlation_config",
        *COMMON(),
        sa.Column("dedup_window_seconds", sa.Integer(), nullable=False),
        sa.Column("correlation_window_seconds", sa.Integer(), nullable=False),
        sa.Column("group_attrs", JsonType, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("correlation_config")
    op.drop_table("incident_events")
    op.drop_table("alert_events")
    op.drop_table("incidents")
    sa.Enum(name="incident_status").drop(op.get_bind(), checkfirst=True)
