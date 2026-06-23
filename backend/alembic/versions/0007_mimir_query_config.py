"""mimir_query_config: single-row admin config for the label-discovery proxy.

Additive on the IMP baseline (0001 is pinned to its original table list, so a new
table needs its own migration). Metadata-driven create_all is checkfirst, so this
is idempotent on fresh + existing DBs (mirrors 0002's approach for new tables).
The default row (label_query_lookback_hours=1) is seeded lazily by the
get_mimir_query_config get-or-create helper, not here.
"""

from collections.abc import Sequence

from alembic import op
from app.models import Base
from app.models.mimir import MimirQueryConfig

revision: str = "0007_mimir_query_config"
down_revision: str | None = "0006_group_labels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [MimirQueryConfig.__table__]


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind(), tables=_TABLES)
