"""notifications.incident_id -> nullable + ON DELETE SET NULL.

Deleting (dissolving) an incident keeps its already-sent/dead notifications as a
delivery record (incident_id NULLed); pending/failed are deleted first by
incident_service.delete_incident. Batch-altered for SQLite/PG parity.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_notif_incident_nullable"
down_revision: str | None = "0003_drop_rule_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE notifications ALTER COLUMN incident_id DROP NOT NULL")
        op.drop_constraint("notifications_incident_id_fkey", "notifications", type_="foreignkey")
        op.create_foreign_key(
            "notifications_incident_id_fkey",
            "notifications",
            "incidents",
            ["incident_id"],
            ["id"],
            ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("notifications") as batch:
            batch.alter_column("incident_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("notifications_incident_id_fkey", "notifications", type_="foreignkey")
        op.create_foreign_key(
            "notifications_incident_id_fkey",
            "notifications",
            "incidents",
            ["incident_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.execute("ALTER TABLE notifications ALTER COLUMN incident_id SET NOT NULL")
    else:
        with op.batch_alter_table("notifications") as batch:
            batch.alter_column("incident_id", existing_type=sa.Uuid(), nullable=False)
