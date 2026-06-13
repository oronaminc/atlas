"""notification scale: priority column + partial claim index

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-13

- notifications.priority smallint (0=critical, 1=warning, 2=info), backfilled
  from each row's incident severity.
- ix_notifications_claim becomes a PARTIAL index
  (tenant_id, priority, created_at) WHERE status IN ('pending','failed') on PG
  — that's what turns the claim from an 861ms seq-scan+sort (Phase 1/4
  baseline @1.3M pending) into a tenant-local index-ordered scan. SQLite keeps
  the plain index (no partial-index perf concern in tests).

0001 pre-creates current columns/indexes from metadata on fresh DBs, so every
step is inspector-guarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLAIM_INDEX = "ix_notifications_claim"
PARTIAL_WHERE = "status IN ('pending', 'failed')"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    cols = {c["name"] for c in inspector.get_columns("notifications")}
    if "priority" not in cols:
        op.add_column(
            "notifications",
            sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        )

    # backfill priority from incident severity
    if is_pg:
        bind.execute(
            sa.text(
                "UPDATE notifications n SET priority = CASE i.severity "
                "WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END "
                "FROM incidents i WHERE n.incident_id = i.id"
            )
        )
    else:
        bind.execute(
            sa.text(
                "UPDATE notifications SET priority = ("
                "SELECT CASE i.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END "
                "FROM incidents i WHERE i.id = notifications.incident_id) "
                "WHERE incident_id IS NOT NULL"
            )
        )

    existing_indexes = {i["name"] for i in inspector.get_indexes("notifications")}
    if is_pg:
        # replace whatever ix_notifications_claim exists (metadata-created plain
        # index on fresh DBs) with the PARTIAL one the claim query needs
        if CLAIM_INDEX in existing_indexes:
            op.drop_index(CLAIM_INDEX, table_name="notifications")
        op.execute(
            f"CREATE INDEX {CLAIM_INDEX} ON notifications "
            f"(tenant_id, priority, created_at) WHERE {PARTIAL_WHERE}"
        )
    else:
        if CLAIM_INDEX not in existing_indexes:
            op.create_index(CLAIM_INDEX, "notifications", ["tenant_id", "priority", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if CLAIM_INDEX in {i["name"] for i in inspector.get_indexes("notifications")}:
        op.drop_index(CLAIM_INDEX, table_name="notifications")
    if "priority" in {c["name"] for c in inspector.get_columns("notifications")}:
        op.drop_column("notifications", "priority")
