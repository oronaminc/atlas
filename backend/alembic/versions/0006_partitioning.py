"""alert_events daily partitioning + retention_config + alert_stats_hourly

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-13

Populated-table conversion (PG only) via rename+ATTACH:
  1. CHECK (received_at < cutover) NOT VALID -> VALIDATE (proves the range
     so ATTACH skips its scan)
  2. rename table+indexes -> *_legacy, CREATE partitioned parent
     (PK(id, received_at) — partitioned tables cannot have a global PK(id)),
     ATTACH legacy FOR VALUES FROM (MINVALUE) TO (cutover)
  3. daily partitions today..+7 + DEFAULT partition (inserts never fail)

The write-lock window = the rename->attach transaction; its cost is the
unique (id, received_at) index build on the legacy data (measured on a
10M-row table by the load harness; see CLAUDE.md). Matching secondary
indexes are attached, not rebuilt. Fallback for >=100M rows: full-copy +
dual-write (not implemented; documented in the Phase 3 design).

SQLite (tests): only the two new tables; partitioning is a PG concern.
"""

import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARENT_INDEXES = [
    ("ix_alert_events_fp_received", ["fingerprint", "received_at"]),
    ("ix_alert_events_tenant_received", ["tenant_id", "received_at"]),
    ("ix_alert_events_fingerprint", ["fingerprint"]),
    ("ix_alert_events_source", ["source"]),
    ("ix_alert_events_received_at", ["received_at"]),
    ("ix_alert_events_incident_id", ["incident_id"]),
    ("ix_alert_events_tenant_id", ["tenant_id"]),
]


def _create_new_tables(inspector) -> None:
    tables = set(inspector.get_table_names())
    if "retention_config" not in tables:
        op.create_table(
            "retention_config",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("alert_events_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("incidents_days", sa.Integer(), nullable=False, server_default="180"),
            sa.Column("notifications_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("audit_days", sa.Integer(), nullable=False, server_default="365"),
            sa.Column("archive_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
        )
    if "alert_stats_hourly" not in tables:
        op.create_table(
            "alert_stats_hourly",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("updated_by", sa.Uuid(), nullable=True),
        )
        op.create_index("ix_alert_stats_hourly_bucket", "alert_stats_hourly", ["bucket_start"])
        op.create_index(
            "ix_alert_stats_hourly_tenant_bucket",
            "alert_stats_hourly",
            ["tenant_id", "bucket_start"],
        )
        op.create_index("ix_alert_stats_hourly_tenant_id", "alert_stats_hourly", ["tenant_id"])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _create_new_tables(inspector)

    if bind.dialect.name != "postgresql":
        return

    relkind = bind.execute(
        sa.text(
            "SELECT c.relkind::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'alert_events' AND n.nspname = current_schema()"
        )
    ).scalar()
    if relkind != "r":  # missing or already partitioned
        return

    cutover = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cut = f"{cutover:%Y-%m-%d}"

    # NOTE: alembic runs this in ONE transaction, so the write-lock window
    # is first-DDL -> COMMIT. Cost drivers: the CHECK validation scan + the
    # unique (id, received_at) index build on the legacy data.
    t0 = time.monotonic()

    # 1. prove the legacy range (ATTACH will skip its validation scan)
    bind.execute(
        sa.text(
            f"ALTER TABLE alert_events ADD CONSTRAINT ck_legacy_range "
            f"CHECK (received_at < '{cut}') NOT VALID"
        )
    )
    bind.execute(sa.text("ALTER TABLE alert_events VALIDATE CONSTRAINT ck_legacy_range"))

    # 2. rename -> PK swap -> parent -> attach
    bind.execute(sa.text("ALTER TABLE alert_events RENAME TO alert_events_legacy"))
    legacy_indexes = bind.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'alert_events_legacy' "
            "AND schemaname = current_schema()"
        )
    ).scalars()
    for name in list(legacy_indexes):
        if not name.endswith("_legacy"):
            bind.execute(sa.text(f"ALTER INDEX {name} RENAME TO {name}_legacy"))

    # legacy PK(id) -> PK(id, received_at) so ATTACH can adopt the parent's
    # PK instead of trying to add a second one (the index build is the bulk
    # of the lock window on populated tables)
    pk_name = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint WHERE contype = 'p' "
            "AND conrelid = 'alert_events_legacy'::regclass"
        )
    ).scalar()
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX alert_events_legacy_pk2 "
            "ON alert_events_legacy (id, received_at)"
        )
    )
    bind.execute(sa.text(f"ALTER TABLE alert_events_legacy DROP CONSTRAINT {pk_name}"))
    bind.execute(
        sa.text(
            "ALTER TABLE alert_events_legacy "
            "ADD CONSTRAINT alert_events_legacy_pk2 PRIMARY KEY USING INDEX alert_events_legacy_pk2"
        )
    )

    bind.execute(
        sa.text(
            "CREATE TABLE alert_events (LIKE alert_events_legacy INCLUDING DEFAULTS) "
            "PARTITION BY RANGE (received_at)"
        )
    )
    bind.execute(sa.text("ALTER TABLE alert_events ADD PRIMARY KEY (id, received_at)"))
    bind.execute(
        sa.text(
            "ALTER TABLE alert_events ADD CONSTRAINT alert_events_incident_id_fkey "
            "FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE SET NULL"
        )
    )
    for name, cols in PARENT_INDEXES:
        bind.execute(sa.text(f"CREATE INDEX {name} ON alert_events ({', '.join(cols)})"))

    bind.execute(
        sa.text(
            "ALTER TABLE alert_events ATTACH PARTITION alert_events_legacy "
            f"FOR VALUES FROM (MINVALUE) TO ('{cut}')"
        )
    )
    lock_window = time.monotonic() - t0
    print(f"0006: conversion lock window (first DDL -> attach) = {lock_window:.1f}s")

    # 3. partitions ahead + DEFAULT (inserts never fail on a missing date)
    day = cutover - timedelta(days=1)  # today (rows < cutover route to legacy,
    # but create today's partition anyway for re-runs after legacy drops)
    for offset in range(0, 9):
        d = day + timedelta(days=offset)
        if d < cutover:
            continue  # overlaps the legacy range
        bind.execute(
            sa.text(
                f"CREATE TABLE IF NOT EXISTS alert_events_p{d:%Y%m%d} "
                f"PARTITION OF alert_events "
                f"FOR VALUES FROM ('{d:%Y-%m-%d}') TO ('{d + timedelta(days=1):%Y-%m-%d}')"
            )
        )
    bind.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS alert_events_default " "PARTITION OF alert_events DEFAULT"
        )
    )


def downgrade() -> None:
    # partition conversion is one-way by design (legacy data ages out);
    # only the additive tables are reversible.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "alert_stats_hourly" in tables:
        op.drop_table("alert_stats_hourly")
    if "retention_config" in tables:
        op.drop_table("retention_config")
