"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10

The initial schema is created from the SQLAlchemy metadata, pinned to the
tables that existed at this revision (metadata grows over time; later tables
belong to later migrations). Subsequent migrations use explicit operations.
"""

from collections.abc import Sequence

from alembic import op
from app.models import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_TABLES = [
    "users",
    "groups",
    "user_group",
    "servers",
    "alert_rules",
    "rule_groups",
    "rule_group_rules",
    "notification_policies",
    "receivers",
    "silences",
    "sync_state",
    "audit_logs",
]


def _tables():
    return [Base.metadata.tables[name] for name in INITIAL_TABLES]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_tables())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_tables())
