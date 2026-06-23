"""saml_config: single-row admin config for SAML SSO (SP key/cert + IdP metadata
+ attribute mapping). Additive on the IMP baseline; metadata create_all is
checkfirst, idempotent on fresh + existing DBs (mirrors 0002/0007). The default
row is seeded lazily by get_saml_config, not here.
"""

from collections.abc import Sequence

from alembic import op
from app.models import Base
from app.models.saml import SamlConfig

revision: str = "0008_saml_config"
down_revision: str | None = "0007_mimir_query_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [SamlConfig.__table__]


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), tables=_TABLES)


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind(), tables=_TABLES)
