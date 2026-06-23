"""Drop rule_catalog (threshold filter no longer queries Mimir / parses PromQL).

The per-alertname comparator/base now come from the alert's own annotations or
the cached Mimir rule (mimir_rules) — rule_catalog + value_query are gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_drop_rule_catalog"
down_revision: str | None = "0002_mimir_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("rule_catalog"):
        op.drop_table("rule_catalog")


def downgrade() -> None:
    op.create_table(
        "rule_catalog",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alertname", sa.String(255), nullable=False),
        sa.Column("comparator", sa.String(2), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("value_query", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.UniqueConstraint("alertname", name="uq_rule_catalog_alertname"),
    )
