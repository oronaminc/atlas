"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10

The initial schema is created directly from the SQLAlchemy metadata so it
stays in perfect parity with app.models. Subsequent migrations must use
explicit alembic operations.
"""

from collections.abc import Sequence

from alembic import op

from app.models import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
