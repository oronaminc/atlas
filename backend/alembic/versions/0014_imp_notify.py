"""IMP stage 5: notifications.recipient_user_id nullable (OnCall team rows).

OnCall is a team webhook (no per-user recipient) — one outbox row per incident
with recipient_user_id NULL. Batch alter for SQLite + PG parity.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notifications") as b:
        b.alter_column("recipient_user_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("notifications") as b:
        b.alter_column("recipient_user_id", existing_type=sa.Uuid(), nullable=False)
