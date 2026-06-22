"""IMP redesign stage 1: schema foundation round-trips (additive, no behavior
change yet). Verifies the new tables/columns exist and persist, and that the
severity-aware formation helper on GroupingRule is correct."""

from sqlalchemy import select

from app.models import GroupingRule, GroupServiceCode, NotificationDefault
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.base import utcnow
from app.models.group import Group
from app.models.threshold import RuleCatalog, ThresholdOverride

NOW = utcnow()


async def test_alert_denorm_columns_round_trip(db):
    ev = AlertEvent(
        fingerprint="fp",
        source="alertmanager",
        name="HostHighCpuLoad",
        severity="critical",
        status="firing",
        labels={"cmdb_ci": "CS20260305_1733050772", "cmdb_zone": "둔산_10F_D1"},
        annotations={},
        starts_at=NOW,
        received_at=NOW,
        cmdb_ci="CS20260305_1733050772",
        cmdb_hostname="idv-giantd-builder-001",
        cmdb_zone="둔산_10F_D1",
        client_address="192.168.81.250",
        cmdb_service_l1_code="ssm20240822_00001",
        cmdb_service_l2_code="sub20251126_1040230842",
    )
    db.add(ev)
    await db.flush()
    got = (await db.execute(select(AlertEvent).where(AlertEvent.id == ev.id))).scalar_one()
    assert got.cmdb_service_l2_code == "sub20251126_1040230842"
    assert got.cmdb_zone == "둔산_10F_D1"
    assert got.client_address == "192.168.81.250"


async def test_incident_container_columns_defaults(db):
    inc = Incident(
        title="t",
        status=IncidentStatus.open,
        severity="critical",
        group_key="cmdb_service_l2_code=sub20251126_1040230842",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=0,
        cmdb_service_l2_code="sub20251126_1040230842",
        cmdb_service_l1_code="ssm20240822_00001",
        cmdb_zone="둔산_10F_D1",
    )
    db.add(inc)
    await db.flush()
    got = (await db.execute(select(Incident).where(Incident.id == inc.id))).scalar_one()
    # toggle defaults from the model (email/telegram on, oncall off)
    assert got.notify_email is True and got.notify_telegram is True and got.notify_oncall is False
    assert got.origin == "auto"
    assert got.grouping_rule_id is None
    assert got.cmdb_service_l2_code == "sub20251126_1040230842"


async def test_grouping_rule_severity_aware_threshold(db):
    rule = GroupingRule(name="service-l2")  # defaults: label_keys=[l2], crit_immediate, min=2
    db.add(rule)
    await db.flush()
    got = (await db.execute(select(GroupingRule))).scalar_one()
    assert got.label_keys == ["cmdb_service_l2_code"]
    assert got.window_seconds == 900 and got.min_group_size == 2
    # severity-aware: critical forms at 1, warning/info need 2
    assert got.threshold_for("critical") == 1
    assert got.threshold_for("warning") == 2
    assert got.threshold_for("info") == 2
    # critical_immediate off -> critical also needs min_group_size
    got.critical_immediate = False
    assert got.threshold_for("critical") == 2


async def test_group_service_code_map(db):
    g = Group(name="space-giant-dev")
    db.add(g)
    await db.flush()
    db.add(GroupServiceCode(group_id=g.id, cmdb_service_l2_code="sub20251126_1040230842"))
    db.add(GroupServiceCode(group_id=g.id, cmdb_service_l2_code="sub20251126_OTHER"))
    await db.flush()
    codes = (
        (
            await db.execute(
                select(GroupServiceCode.cmdb_service_l2_code).where(
                    GroupServiceCode.group_id == g.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(codes) == {"sub20251126_1040230842", "sub20251126_OTHER"}


async def test_notification_default_row(db):
    nd = NotificationDefault()
    db.add(nd)
    await db.flush()
    got = (await db.execute(select(NotificationDefault))).scalar_one()
    assert got.default_email is True and got.default_telegram is True
    assert got.default_oncall is False


async def test_threshold_override_label_target(db):
    db.add(RuleCatalog(alertname="HostHighCpuLoad", comparator=">", value_query="q"))
    o = ThresholdOverride(
        alertname="HostHighCpuLoad",
        tier="label",
        target_label_key="cmdb_service_l2_code",
        target_label_value="sub20251126_1040230842",
        value=90.0,
    )
    db.add(o)
    await db.flush()
    got = (await db.execute(select(ThresholdOverride))).scalar_one()
    assert got.target_label_key == "cmdb_service_l2_code"
    assert got.target_label_value == "sub20251126_1040230842"
