"""Mimir read-cache: mimir_rules + mimir_silences (synced from Mimir).

Additive on the IMP baseline; both plain tables on PG + SQLite. Metadata-driven
so the DDL can't drift from the ORM (mirrors 0001's approach for new tables).
"""

from collections.abc import Sequence

from alembic import op
from app.models import Base
from app.models.mimir import MimirRule, MimirSilence

revision: str = "0002_mimir_cache"
down_revision: str | None = "0001_imp_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [MimirRule.__table__, MimirSilence.__table__]


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind(), tables=_TABLES)
