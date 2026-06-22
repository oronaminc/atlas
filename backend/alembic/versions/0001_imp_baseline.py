"""IMP baseline — single fresh schema (collapses the old 0001–0014 chain).

The IMP redesign deploys onto fresh databases, so the whole pre-IMP migration
history (multi-tenancy, servers/rules/mutes, the partitioning *conversion*
dance, etc.) is collapsed into one baseline that creates the FINAL schema.

Strategy:
- Regular tables come straight from the ORM metadata (`Base.metadata`), so the
  baseline can never drift from the models — same shapes tests' create_all uses.
- `alert_events` is the one special case: on PostgreSQL it is RANGE-partitioned
  by `received_at` (daily partitions are created at runtime by the maintenance
  worker; a DEFAULT partition guarantees inserts never fail), with a partition-
  local GIN index on `labels` (jsonb_path_ops) for label search. On SQLite
  (tests) it is an ordinary table — partitioning is a PG-only concern.

This also retires the pre-existing 0010 server_groups FK-ordering bug: that
table and its migration are gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models import Base

revision: str = "0001_imp_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# alert_events parent indexes (propagate to every partition on PG; created
# plainly on SQLite). Mirrors the model's index=True columns + the composite.
_ALERT_EVENT_INDEXES = [
    ("ix_alert_events_fp_received", ["fingerprint", "received_at"]),
    ("ix_alert_events_fingerprint", ["fingerprint"]),
    ("ix_alert_events_source", ["source"]),
    ("ix_alert_events_received_at", ["received_at"]),
    ("ix_alert_events_incident_id", ["incident_id"]),
    ("ix_alert_events_cmdb_ci", ["cmdb_ci"]),
    ("ix_alert_events_cmdb_hostname", ["cmdb_hostname"]),
    ("ix_alert_events_cmdb_zone", ["cmdb_zone"]),
    ("ix_alert_events_client_address", ["client_address"]),
    ("ix_alert_events_cmdb_service_l1_code", ["cmdb_service_l1_code"]),
    ("ix_alert_events_cmdb_service_l2_code", ["cmdb_service_l2_code"]),
]

_ALERT_EVENTS_PG_DDL = """
CREATE TABLE alert_events (
    id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,
    updated_by UUID,
    fingerprint VARCHAR(64) NOT NULL,
    source VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'info',
    status VARCHAR(20) NOT NULL DEFAULT 'firing',
    labels JSONB NOT NULL DEFAULT '{}'::jsonb,
    annotations JSONB NOT NULL DEFAULT '{}'::jsonb,
    starts_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    dedup_count INTEGER NOT NULL DEFAULT 1,
    cmdb_ci VARCHAR(255),
    cmdb_hostname VARCHAR(255),
    cmdb_zone VARCHAR(255),
    client_address VARCHAR(255),
    cmdb_service_l1_code VARCHAR(255),
    cmdb_service_l2_code VARCHAR(255),
    value DOUBLE PRECISION,
    suppressed BOOLEAN NOT NULL DEFAULT false,
    correlated BOOLEAN NOT NULL DEFAULT false,
    claimed_at TIMESTAMPTZ,
    claimed_by VARCHAR(100),
    incident_id UUID REFERENCES incidents(id) ON DELETE SET NULL,
    PRIMARY KEY (id, received_at)
) PARTITION BY RANGE (received_at)
"""


def upgrade() -> None:
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"

    if not pg:
        # SQLite (tests): every table plain, straight from the ORM.
        Base.metadata.create_all(bind)
        return

    # PostgreSQL: everything EXCEPT alert_events from the ORM metadata
    # (incidents must exist first for the FK), then alert_events partitioned.
    others = [t for t in Base.metadata.sorted_tables if t.name != "alert_events"]
    Base.metadata.create_all(bind, tables=others)

    op.execute(_ALERT_EVENTS_PG_DDL)
    op.execute("CREATE TABLE alert_events_default PARTITION OF alert_events DEFAULT")
    for name, cols in _ALERT_EVENT_INDEXES:
        op.create_index(name, "alert_events", cols)
    # label search: GIN (jsonb_path_ops) — PG-only, never built on SQLite.
    op.create_index(
        "ix_alert_events_labels_gin",
        "alert_events",
        ["labels"],
        postgresql_using="gin",
        postgresql_ops={"labels": "jsonb_path_ops"},
    )

    # The notification claim index is PARTIAL on PG (WHERE status claimable) —
    # that's what turns the claim into an index-ordered scan at storm scale.
    # create_all built it plain from the ORM; redefine it here.
    op.drop_index("ix_notifications_claim", table_name="notifications")
    op.create_index(
        "ix_notifications_claim",
        "notifications",
        ["priority", "created_at"],
        postgresql_where=sa.text("status IN ('pending','failed')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS alert_events CASCADE")
    else:
        op.execute("DROP TABLE IF EXISTS alert_events")
    others = [t for t in Base.metadata.sorted_tables if t.name != "alert_events"]
    Base.metadata.drop_all(bind, tables=others)
