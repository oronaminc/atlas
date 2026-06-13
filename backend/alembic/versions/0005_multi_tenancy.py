"""multi-tenancy: tenants + mimir_org_map + tenant_id on scoped tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-13

Decision #4 (conservative): a default tenant is created mapping the legacy
"system" Mimir org, and ALL existing rows AND users are backfilled into it
— nobody loses access; HQ promotes/reassigns users afterwards via the admin
UI (HQ accounts are bootstrapped by scripts/create_admin.py, which creates
tenant_id NULL admins).
"""

import os
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# every TenantScoped table + users (plain column)
TENANT_TABLES = [
    "alert_events",
    "incidents",
    "incident_events",
    "notifications",
    "notification_routes",
    "notification_settings",
    "groups",
    "servers",
    "receivers",
    "notification_policies",
    "silences",
    "alert_rules",
    "rule_groups",
    "audit_logs",
    "sync_state",
    "users",
]

COMPOSITE_INDEXES = [
    ("ix_alert_events_tenant_received", "alert_events", ["tenant_id", "received_at"]),
    ("ix_incidents_tenant_last_seen", "incidents", ["tenant_id", "last_seen"]),
    (
        "ix_notifications_tenant_status_created",
        "notifications",
        ["tenant_id", "status", "created_at"],
    ),
]

BACKFILL_BATCH = 50_000


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. registry tables (0001 pre-creates them on fresh DBs)
    if "tenants" not in tables:
        op.create_table(
            "tenants",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("slug", sa.String(100), nullable=False, unique=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("ingest_key_hash", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
        )
        op.create_index("ix_tenants_ingest_key_hash", "tenants", ["ingest_key_hash"])
    if "mimir_org_map" not in tables:
        op.create_table(
            "mimir_org_map",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("mimir_org", sa.String(200), nullable=False, unique=True),
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
        )
        op.create_index("ix_mimir_org_map_tenant_id", "mimir_org_map", ["tenant_id"])

    # 2. tenant_id columns (nullable: NULL = legacy/system, HQ-visible only)
    for table in TENANT_TABLES:
        if table not in tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "tenant_id" not in cols:
            op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))
            op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    for name, table, cols in COMPOSITE_INDEXES:
        if table in tables:
            existing = {i["name"] for i in inspector.get_indexes(table)}
            if name not in existing:
                op.create_index(name, table, cols)

    # 3. default tenant mapping the legacy "system" org; batched backfill
    default_slug = os.environ.get("ATLAS_DEFAULT_TENANT", "system")
    default_org = os.environ.get("MIMIR_TENANT_ID", "system")
    existing_default = bind.execute(
        sa.text("SELECT id FROM tenants WHERE slug = :slug"), {"slug": default_slug}
    ).scalar()
    if existing_default is None:
        tenant_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO tenants (id, slug, name, is_active, created_at, updated_at) "
                "VALUES (:id, :slug, :name, TRUE, now(), now())"
                if bind.dialect.name == "postgresql"
                else "INSERT INTO tenants (id, slug, name, is_active, created_at, updated_at) "
                "VALUES (:id, :slug, :name, 1, datetime('now'), datetime('now'))"
            ),
            {"id": tenant_id, "slug": default_slug, "name": "Default (legacy system org)"},
        )
        bind.execute(
            sa.text(
                "INSERT INTO mimir_org_map (id, mimir_org, tenant_id, created_at, updated_at) "
                "VALUES (:id, :org, :tid, now(), now())"
                if bind.dialect.name == "postgresql"
                else "INSERT INTO mimir_org_map (id, mimir_org, tenant_id, created_at, updated_at)"
                " VALUES (:id, :org, :tid, datetime('now'), datetime('now'))"
            ),
            {"id": str(uuid.uuid4()), "org": default_org, "tid": tenant_id},
        )
    else:
        tenant_id = str(existing_default)

    for table in TENANT_TABLES:
        if table not in tables:
            continue
        if bind.dialect.name == "postgresql":
            # batched: avoids one long row-lock pass on populated tables
            while True:
                result = bind.execute(
                    sa.text(
                        f"UPDATE {table} SET tenant_id = :tid WHERE id IN ("  # noqa: S608
                        f"SELECT id FROM {table} WHERE tenant_id IS NULL LIMIT :batch)"
                    ),
                    {"tid": tenant_id, "batch": BACKFILL_BATCH},
                )
                if result.rowcount < BACKFILL_BATCH:
                    break
        else:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
                ),  # noqa: S608
                {"tid": tenant_id},
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, _cols in COMPOSITE_INDEXES:
        if table in tables and name in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    for table in TENANT_TABLES:
        if table in tables and "tenant_id" in {c["name"] for c in inspector.get_columns(table)}:
            op.drop_index(f"ix_{table}_tenant_id", table_name=table)
            op.drop_column(table, "tenant_id")
    if "mimir_org_map" in tables:
        op.drop_table("mimir_org_map")
    if "tenants" in tables:
        op.drop_table("tenants")
