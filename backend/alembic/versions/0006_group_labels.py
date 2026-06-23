"""groups.labels (descriptive metadata tags, selected from the Mimir label API).

Guarded/idempotent: the metadata baseline (0001) already adds the column on a
FRESH db, so this only transforms an existing deployment. Default '[]'.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.base import JsonType

revision: str = "0006_group_labels"
down_revision: str | None = "0005_per_group_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("groups")}
    if "labels" not in cols:
        with op.batch_alter_table("groups") as batch:
            batch.add_column(sa.Column("labels", JsonType, nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("groups") as batch:
        batch.drop_column("labels")
