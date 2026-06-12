"""incident suppression: add 'suppressed' to incident_status enum

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PG native enum needs the new value; fresh installs already get it from
    # 0001's metadata-based bootstrap, hence IF NOT EXISTS. SQLite stores the
    # enum as VARCHAR — nothing to do.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE incident_status ADD VALUE IF NOT EXISTS 'suppressed'")


def downgrade() -> None:
    # PG cannot drop a single enum value; suppressed rows would block a type
    # rebuild anyway. Intentional no-op.
    pass
