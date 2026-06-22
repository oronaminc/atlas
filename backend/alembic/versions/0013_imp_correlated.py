"""IMP stage 3: alert_events.correlated terminal marker.

Distinguishes "this alert's arrival has been processed by the topology engine"
(correlated) from "this alert is attached to an incident" (incident_id). A FREE
alert is correlated=True with incident_id NULL: excluded from re-claim, yet still
retro-attachable by a later sibling via a direct UPDATE.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("alert_events")}
    if "correlated" not in cols:
        op.add_column(
            "alert_events",
            sa.Column("correlated", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("alert_events")}
    if "correlated" in cols:
        op.drop_column("alert_events", "correlated")
