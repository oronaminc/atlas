"""LLM analysis (llm_config + incident_analysis) + search GIN index

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-13

Feature A tables + Feature B's GIN index on alert_events.labels
(jsonb_path_ops) for `labels @> {k:v}` label search. The GIN index is
declared on the partitioned parent so PG materializes it partition-local;
PG-only (SQLite tests don't need it). 0001 pre-creates current columns on
fresh DBs, so the table creates are inspector-guarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GIN_INDEX = "ix_alert_events_labels_gin"


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
    is_pg = bind.dialect.name == "postgresql"

    if "llm_config" not in tables:
        op.create_table(
            "llm_config",
            *_common(),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("api_key", sa.Text(), nullable=True),
            sa.Column("model", sa.String(200), nullable=False, server_default=""),
            sa.Column("max_prompt_chars", sa.Integer(), nullable=False, server_default="12000"),
            sa.Column("max_completion_tokens", sa.Integer(), nullable=False, server_default="512"),
            sa.Column("daily_quota", sa.Integer(), nullable=False, server_default="200"),
            sa.Column("auto_analyze", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "redact_external_strict", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )
        op.create_index("ix_llm_config_tenant_id", "llm_config", ["tenant_id"])

    if "incident_analysis" not in tables:
        op.create_table(
            "incident_analysis",
            *_common(),
            sa.Column(
                "incident_id",
                sa.Uuid(),
                sa.ForeignKey("incidents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("prompt_hash", sa.String(64), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column("model", sa.String(200), nullable=True),
            sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claimed_by", sa.String(100), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("incident_id", name="uq_incident_analysis"),
        )
        op.create_index("ix_incident_analysis_incident_id", "incident_analysis", ["incident_id"])
        op.create_index("ix_incident_analysis_tenant_id", "incident_analysis", ["tenant_id"])

    # search: GIN on labels (PG only)
    if is_pg:
        existing = {i["name"] for i in inspector.get_indexes("alert_events")}
        if GIN_INDEX not in existing:
            op.execute(
                f"CREATE INDEX {GIN_INDEX} ON alert_events " "USING gin (labels jsonb_path_ops)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "postgresql":
        if GIN_INDEX in {i["name"] for i in inspector.get_indexes("alert_events")}:
            op.drop_index(GIN_INDEX, table_name="alert_events")
    for tbl in ("incident_analysis", "llm_config"):
        if tbl in set(inspector.get_table_names()):
            op.drop_table(tbl)
