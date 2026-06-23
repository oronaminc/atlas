from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class SamlConfig(TimestampedBase):
    """Single row, admin-managed SAML SP config. enabled=False until configured
    (nothing active). sp_private_key is Fernet-encrypted at rest and MASKED in
    responses; sp_certificate + idp_metadata_xml are public. Attribute names are
    the values the IdP emits (TiDC: givenName / distinguishedName / mail)."""

    __tablename__ = "saml_config"

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sp_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    sp_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)  # public
    idp_metadata_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name_attr: Mapped[str] = mapped_column(String(100), default="givenName")
    uid_attr: Mapped[str] = mapped_column(String(100), default="distinguishedName")
    email_attr: Mapped[str] = mapped_column(String(100), default="mail")
