"""IMP redesign stage 1: label-based schema foundation (additive).

Adds the incident-management-platform schema alongside the existing tables
(expand phase — legacy tables, tenancy removal, and the baseline collapse land
in the cleanup stage):
  - alert_events: 6 denormalized topology/identity label columns
  - incidents: per-incident channel toggles + denorm topology + origin + rule fk
  - grouping_rules (topology criteria; severity-aware formation)
  - group_service_codes (user-group -> cmdb_service_l2_code map, 1:N)
  - notification_defaults (default channel toggles)
  - notification_settings: oncall webhook + token
  - threshold_overrides: label-scoped target (key/value)

Inspector-guarded (0001 is metadata-pinned; new tables/columns guarded so a
fresh DB and an existing DB both converge).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# audit columns common to every new (non-tenant-scoped) table
_AUDIT = [
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    sa.Column("created_by", sa.Uuid(), nullable=True),
    sa.Column("updated_by", sa.Uuid(), nullable=True),
]

_ALERT_DENORM = [
    "cmdb_ci",
    "cmdb_hostname",
    "cmdb_zone",
    "client_address",
    "cmdb_service_l1_code",
    "cmdb_service_l2_code",
]


def _cols(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # --- alert_events denorm columns ---
    ae = _cols(inspector, "alert_events")
    for col in _ALERT_DENORM:
        if col not in ae:
            op.add_column("alert_events", sa.Column(col, sa.String(255), nullable=True))
            op.create_index(f"ix_alert_events_{col}", "alert_events", [col])

    # --- incidents container columns ---
    inc = _cols(inspector, "incidents")
    if "notify_email" not in inc:
        op.add_column(
            "incidents",
            sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "notify_telegram" not in inc:
        op.add_column(
            "incidents",
            sa.Column("notify_telegram", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "notify_oncall" not in inc:
        op.add_column(
            "incidents",
            sa.Column("notify_oncall", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "cmdb_service_l2_code" not in inc:
        op.add_column("incidents", sa.Column("cmdb_service_l2_code", sa.String(255), nullable=True))
        op.create_index("ix_incidents_cmdb_service_l2_code", "incidents", ["cmdb_service_l2_code"])
    if "cmdb_service_l1_code" not in inc:
        op.add_column("incidents", sa.Column("cmdb_service_l1_code", sa.String(255), nullable=True))
    if "cmdb_zone" not in inc:
        op.add_column("incidents", sa.Column("cmdb_zone", sa.String(255), nullable=True))
    if "origin" not in inc:
        op.add_column(
            "incidents",
            sa.Column("origin", sa.String(10), nullable=False, server_default="auto"),
        )
    if "grouping_rule_id" not in inc:
        op.add_column("incidents", sa.Column("grouping_rule_id", sa.Uuid(), nullable=True))

    # --- grouping_rules ---
    if "grouping_rules" not in tables:
        op.create_table(
            "grouping_rules",
            *_AUDIT,
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("label_keys", sa.JSON(), nullable=True),
            sa.Column("match", sa.JSON(), nullable=True),
            sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="900"),
            sa.Column("min_group_size", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("critical_immediate", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("dedup_window_seconds", sa.Integer(), nullable=False, server_default="300"),
            sa.UniqueConstraint("name", name="uq_grouping_rule_name"),
        )
        op.create_index("ix_grouping_rules_name", "grouping_rules", ["name"])

    # --- group_service_codes (user-group -> l2_code) ---
    if "group_service_codes" not in tables:
        op.create_table(
            "group_service_codes",
            *_AUDIT,
            sa.Column(
                "group_id",
                sa.Uuid(),
                sa.ForeignKey("groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("cmdb_service_l2_code", sa.String(255), nullable=False),
            sa.UniqueConstraint("group_id", "cmdb_service_l2_code", name="uq_group_service_code"),
        )
        op.create_index("ix_group_service_codes_group_id", "group_service_codes", ["group_id"])
        op.create_index(
            "ix_group_service_codes_cmdb_service_l2_code",
            "group_service_codes",
            ["cmdb_service_l2_code"],
        )

    # --- notification_defaults ---
    if "notification_defaults" not in tables:
        op.create_table(
            "notification_defaults",
            *_AUDIT,
            sa.Column("default_email", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("default_telegram", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("default_oncall", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # --- notification_settings: oncall ---
    ns = _cols(inspector, "notification_settings")
    if "oncall_webhook_url" not in ns:
        op.add_column(
            "notification_settings", sa.Column("oncall_webhook_url", sa.Text(), nullable=True)
        )
    if "oncall_token" not in ns:
        op.add_column("notification_settings", sa.Column("oncall_token", sa.Text(), nullable=True))

    # --- threshold_overrides: label-scoped target ---
    to = _cols(inspector, "threshold_overrides")
    if "target_label_key" not in to:
        op.add_column(
            "threshold_overrides", sa.Column("target_label_key", sa.String(100), nullable=True)
        )
    if "target_label_value" not in to:
        op.add_column(
            "threshold_overrides",
            sa.Column("target_label_value", sa.String(255), nullable=True),
        )
        op.create_index(
            "ix_threshold_overrides_target_label_value",
            "threshold_overrides",
            ["target_label_value"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for tbl in ("group_service_codes", "notification_defaults", "grouping_rules"):
        if tbl in tables:
            op.drop_table(tbl)

    to = _cols(inspector, "threshold_overrides")
    for col in ("target_label_value", "target_label_key"):
        if col in to:
            op.drop_column("threshold_overrides", col)

    ns = _cols(inspector, "notification_settings")
    for col in ("oncall_token", "oncall_webhook_url"):
        if col in ns:
            op.drop_column("notification_settings", col)

    inc = _cols(inspector, "incidents")
    for col in (
        "grouping_rule_id",
        "origin",
        "cmdb_zone",
        "cmdb_service_l1_code",
        "cmdb_service_l2_code",
        "notify_oncall",
        "notify_telegram",
        "notify_email",
    ):
        if col in inc:
            op.drop_column("incidents", col)

    ae = _cols(inspector, "alert_events")
    for col in _ALERT_DENORM:
        if col in ae:
            op.drop_column("alert_events", col)
