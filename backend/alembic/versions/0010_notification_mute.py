"""Notification mute + server master data (cmdb_ci) + server groups

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-18

PR #1 (mute): server_groups (logical/notification unit), servers.cmdb_ci +
servers.server_group_id (1:1 membership), notification_mutes (target x
alertname, wildcards). Inspector-guarded (0001 pre-creates current columns on
fresh DBs); add_column/index guarded so re-runs and fresh DBs both work.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "server_groups" not in tables:
        op.create_table(
            "server_groups",
            *_common(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.UniqueConstraint("tenant_id", "name", name="uq_server_group_name"),
        )
        op.create_index("ix_server_groups_name", "server_groups", ["name"])
        op.create_index("ix_server_groups_tenant_id", "server_groups", ["tenant_id"])

    # extend servers (guard each column — fresh DB from 0001 may already lack them)
    server_cols = {c["name"] for c in inspector.get_columns("servers")}
    if "cmdb_ci" not in server_cols:
        op.add_column("servers", sa.Column("cmdb_ci", sa.String(255), nullable=True))
        op.create_index("ix_servers_cmdb_ci", "servers", ["cmdb_ci"])
        op.create_unique_constraint("uq_server_cmdb_ci", "servers", ["tenant_id", "cmdb_ci"])
    if "server_group_id" not in server_cols:
        op.add_column(
            "servers",
            sa.Column(
                "server_group_id",
                sa.Uuid(),
                sa.ForeignKey("server_groups.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_servers_server_group_id", "servers", ["server_group_id"])

    if "notification_mutes" not in tables:
        op.create_table(
            "notification_mutes",
            *_common(),
            sa.Column("target_type", sa.String(10), nullable=False, server_default="server"),
            sa.Column("target_cmdb_ci", sa.String(255), nullable=True),
            sa.Column(
                "target_group_id",
                sa.Uuid(),
                sa.ForeignKey("server_groups.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("alertname", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "target_type",
                "target_cmdb_ci",
                "target_group_id",
                "alertname",
                name="uq_notification_mute",
            ),
        )
        op.create_index("ix_notification_mutes_tenant_id", "notification_mutes", ["tenant_id"])
        op.create_index("ix_notification_mutes_target_type", "notification_mutes", ["target_type"])
        op.create_index(
            "ix_notification_mutes_target_cmdb_ci", "notification_mutes", ["target_cmdb_ci"]
        )
        op.create_index("ix_notification_mutes_alertname", "notification_mutes", ["alertname"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "notification_mutes" in tables:
        op.drop_table("notification_mutes")
    server_cols = {c["name"] for c in inspector.get_columns("servers")}
    if "server_group_id" in server_cols:
        op.drop_column("servers", "server_group_id")
    if "cmdb_ci" in server_cols:
        op.drop_constraint("uq_server_cmdb_ci", "servers", type_="unique")
        op.drop_column("servers", "cmdb_ci")
    if "server_groups" in tables:
        op.drop_table("server_groups")
