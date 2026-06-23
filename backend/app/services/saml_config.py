from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saml import SamlConfig


async def get_saml_config(db: AsyncSession) -> SamlConfig:
    """Single-row admin SAML config; seeds defaults on first access
    (enabled=False; givenName / distinguishedName / mail). DB is authoritative."""
    row = (await db.execute(select(SamlConfig).limit(1))).scalar_one_or_none()
    if row is None:
        row = SamlConfig()
        db.add(row)
        await db.flush()
    return row
