"""Per-group notification channels: + group_channels, notifications.group_channel_id,
dedup key -> recipient_address, drop the global notification_settings.

All guarded/idempotent: the metadata baseline (0001) already builds the final
shape on a FRESH db, so each step is a no-op there and only transforms an
existing (pre-overhaul) deployment. Dev data is disposable; no data backfill
for the old global oncall_webhook_url / telegram_bot_token (they move to
per-group config, configured fresh in Channel assignment).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.delivery import GroupChannel

revision: str = "0005_per_group_channels"
down_revision: str | None = "0004_notif_incident_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("group_channels"):
        GroupChannel.__table__.create(bind)

    cols = {c["name"] for c in insp.get_columns("notifications")}
    if "group_channel_id" not in cols:
        with op.batch_alter_table("notifications") as batch:
            batch.add_column(sa.Column("group_channel_id", sa.Uuid(), nullable=True))

    # swap the dedup unique: (incident, channel, recipient_user_id) -> recipient_address
    uniques = {u["name"] for u in insp.get_unique_constraints("notifications")}
    if bind.dialect.name == "postgresql" and "uq_notification_target" in uniques:
        cols_now = {
            tuple(u["column_names"])
            for u in insp.get_unique_constraints("notifications")
            if u["name"] == "uq_notification_target"
        }
        if ("incident_id", "channel", "recipient_address") not in cols_now:
            op.drop_constraint("uq_notification_target", "notifications", type_="unique")
            op.create_unique_constraint(
                "uq_notification_target",
                "notifications",
                ["incident_id", "channel", "recipient_address"],
            )

    if insp.has_table("notification_settings"):
        op.drop_table("notification_settings")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("group_channels"):
        op.drop_table("group_channels")
    cols = {c["name"] for c in insp.get_columns("notifications")}
    if "group_channel_id" in cols:
        with op.batch_alter_table("notifications") as batch:
            batch.drop_column("group_channel_id")
