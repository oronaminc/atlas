"""users: SAML JIT fields (saml_uid match key + display_name) and the 'saml'
auth_provider enum value.

Guarded/idempotent: the metadata baseline (0001) pre-creates current columns +
enum members on a FRESH db, so this only transforms an EXISTING deployment. The
column adds are inspector-guarded; the PG enum value is added IF NOT EXISTS
(PG-only; SQLite stores the enum as VARCHAR and gets the new member via the model).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_saml_user_fields"
down_revision: str | None = "0008_saml_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "saml_uid" not in cols:
            batch.add_column(sa.Column("saml_uid", sa.String(length=512), nullable=True))
        if "display_name" not in cols:
            batch.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
    if "saml_uid" not in cols:
        op.create_index("ix_users_saml_uid", "users", ["saml_uid"])
    # PG enum: add 'saml' (no-op if already present, e.g. fresh DB created from the
    # current model). SQLite path is a VARCHAR -> nothing to alter.
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE auth_provider ADD VALUE IF NOT EXISTS 'saml'")


def downgrade() -> None:
    # PG cannot drop an enum value; leave 'saml' in place. Drop the columns only.
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "saml_uid" in cols:
        op.drop_index("ix_users_saml_uid", table_name="users")
    with op.batch_alter_table("users") as batch:
        if "display_name" in cols:
            batch.drop_column("display_name")
        if "saml_uid" in cols:
            batch.drop_column("saml_uid")
