"""Threshold overrides: rule_catalog + threshold_overrides + alert_events.value

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-19

PR #2 (threshold filter, Model 2). Ingest-time per-server/per-group threshold
overrides evaluated against the live Mimir value. Inspector-guarded (0001
pre-creates current columns on fresh DBs; new tables/columns are guarded).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "rule_catalog" not in tables:
        op.create_table(
            "rule_catalog",
            *_common(),
            sa.Column("alertname", sa.String(255), nullable=False),
            sa.Column("comparator", sa.String(2), nullable=True),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("value_query", sa.Text(), nullable=True),
            sa.UniqueConstraint("tenant_id", "alertname", name="uq_rule_catalog_alertname"),
        )
        op.create_index("ix_rule_catalog_alertname", "rule_catalog", ["alertname"])
        op.create_index("ix_rule_catalog_tenant_id", "rule_catalog", ["tenant_id"])

    if "threshold_overrides" not in tables:
        op.create_table(
            "threshold_overrides",
            *_common(),
            sa.Column("alertname", sa.String(255), nullable=False),
            sa.Column("tier", sa.String(10), nullable=False),
            sa.Column("target_cmdb_ci", sa.String(255), nullable=True),
            sa.Column("target_group_id", sa.Uuid(), nullable=True),
            sa.Column("value", sa.Float(), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "alertname",
                "tier",
                "target_cmdb_ci",
                "target_group_id",
                name="uq_threshold_override",
            ),
        )
        for col in ("alertname", "tier", "target_cmdb_ci", "target_group_id", "tenant_id"):
            op.create_index(f"ix_threshold_overrides_{col}", "threshold_overrides", [col])

    cols = {c["name"] for c in inspector.get_columns("alert_events")}
    if "value" not in cols:
        op.add_column("alert_events", sa.Column("value", sa.Float(), nullable=True))
    if "suppressed" not in cols:
        op.add_column(
            "alert_events",
            sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    ae_cols = {c["name"] for c in inspector.get_columns("alert_events")}
    if "suppressed" in ae_cols:
        op.drop_column("alert_events", "suppressed")
    if "value" in ae_cols:
        op.drop_column("alert_events", "value")
    for tbl in ("threshold_overrides", "rule_catalog"):
        if tbl in tables:
            op.drop_table(tbl)
