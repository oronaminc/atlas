"""Retention config API (HQ-admin) + retention deletes + hourly rollups +
stats endpoints reading rollups. Partition mechanics are PG-only and live
in tests/pg/test_partitioning.py."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.audit import AuditLog
from app.models.delivery import Notification
from app.models.maintenance import AlertStatsHourly
from app.models.user import GlobalRole
from app.services.maintenance import (
    delete_expired_rows,
    get_retention_config,
    rollup_hourly,
)
from tests.conftest import auth_headers, make_user

NOW = datetime(2026, 6, 13, 12, 30, 0, tzinfo=UTC)


def event(received_at, severity="warning", tenant_id=None, fp="f1"):
    return AlertEvent(
        fingerprint=fp,
        source="alertmanager",
        name="A",
        severity=severity,
        status="firing",
        labels={},
        annotations={},
        starts_at=received_at,
        received_at=received_at,
        tenant_id=tenant_id,
        cmdb_service_l2_code="L2TEST",
    )


# --- config API ---


async def test_retention_config_defaults_and_hq_admin_update(client, admin, viewer):
    res = await client.get("/api/v1/retention-config", headers=auth_headers(admin))
    assert res.status_code == 200
    data = res.json()["data"]
    assert data == {
        "alert_events_days": 90,
        "incidents_days": 180,
        "notifications_days": 90,
        "audit_days": 365,
        "archive_enabled": False,
    }

    res = await client.patch(
        "/api/v1/retention-config",
        json={"alert_events_days": 30, "archive_enabled": True},
        headers=auth_headers(admin),
    )
    assert res.status_code == 200
    assert res.json()["data"]["alert_events_days"] == 30
    assert res.json()["data"]["archive_enabled"] is True

    # audited
    res = await client.get(
        "/api/v1/audit-logs?resource_type=retention_config", headers=auth_headers(admin)
    )
    assert [e["action"] for e in res.json()["data"]] == ["update"]

    # viewer cannot read; non-admin cannot write
    res = await client.get("/api/v1/retention-config", headers=auth_headers(viewer))
    assert res.status_code == 403


async def test_retention_update_is_hq_admin_only(client, db, admin, tenant_a, a_admin):
    res = await client.patch(
        "/api/v1/retention-config",
        json={"audit_days": 1},
        headers=auth_headers(a_admin),
    )
    assert res.status_code == 403  # tenant-admin blocked
    res = await client.get("/api/v1/retention-config", headers=auth_headers(a_admin))
    assert res.status_code == 200  # read-only visibility


# --- retention deletes ---


async def test_delete_expired_rows_respects_policy(client, db, admin):
    old = NOW - timedelta(days=200)
    fresh = NOW - timedelta(days=1)
    incidents = []
    for last_seen, status in [
        (old, IncidentStatus.resolved),
        (old, IncidentStatus.suppressed),
        (old, IncidentStatus.open),  # old but OPEN -> must survive
        (fresh, IncidentStatus.resolved),  # fresh -> must survive
    ]:
        incident = Incident(
            title=f"i-{status}-{last_seen:%j}",
            status=status,
            severity="info",
            group_key="host=x",
            first_seen=last_seen,
            last_seen=last_seen,
            alert_count=0,
        )
        db.add(incident)
        incidents.append(incident)
    user = await make_user(db, "rcpt@example.com", GlobalRole.viewer)
    await db.flush()
    for i, (addr, status, age) in enumerate([("1", "sent", 120), ("2", "pending", 120)]):
        db.add(
            Notification(
                incident_id=incidents[-1 - i].id,  # unique (incident, channel, user)
                channel="telegram",
                recipient_user_id=user.id,
                recipient_address=addr,
                status=status,  # old pending -> survives
                created_at=NOW - timedelta(days=age),
            )
        )
    db.add(AuditLog(action="x", resource_type="t", created_at=NOW - timedelta(days=400)))
    await db.commit()

    config = await get_retention_config(db)
    # freeze "now" semantics by computing cutoffs from utcnow inside; ages
    # above are relative to real now too (NOW ~= today in this test file)
    deleted = await delete_expired_rows(db, config)
    await db.commit()

    assert deleted["incidents"] == 2  # resolved+suppressed older than 180d
    assert deleted["notifications"] == 1
    assert deleted["audit_logs"] >= 1

    statuses = [i.status for i in (await db.execute(select(Incident))).scalars()]
    assert IncidentStatus.open in statuses  # old open incident kept
    remaining = [n.status for n in (await db.execute(select(Notification))).scalars()]
    assert remaining == ["pending"]


async def test_zero_days_means_keep_forever(db):
    db.add(AuditLog(action="x", resource_type="t", created_at=NOW - timedelta(days=4000)))
    await db.commit()
    config = await get_retention_config(db)
    config.audit_days = 0
    deleted = await delete_expired_rows(db, config)
    assert "audit_logs" not in deleted


# --- rollups + stats ---


async def test_rollup_hourly_is_idempotent_and_tenant_tagged(db, tenant_a, tenant_b):
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    for i in range(3):
        db.add(event(base + timedelta(minutes=i), "critical", tenant_a.id, fp=f"a{i}"))
    db.add(event(base + timedelta(minutes=5), "warning", tenant_b.id, fp="b0"))
    await db.commit()

    n1 = await rollup_hourly(db)
    await db.commit()
    n2 = await rollup_hourly(db)  # rerun must not duplicate
    await db.commit()
    assert n1 == n2 == 2

    rows = (await db.execute(select(AlertStatsHourly))).scalars().all()
    by_tenant = {(r.tenant_id, r.severity): r.count for r in rows}
    assert by_tenant[(tenant_a.id, "critical")] == 3
    assert by_tenant[(tenant_b.id, "warning")] == 1


async def test_stats_read_rollups_plus_live_tail(client, db, viewer):
    now = datetime.now(UTC)
    closed_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    # 5 events in a closed hour (rolled up), 2 live in the current hour
    for i in range(5):
        db.add(event(closed_hour + timedelta(minutes=i), "critical", fp=f"c{i}"))
    for i in range(2):
        db.add(event(now - timedelta(minutes=1 + i), "info", fp=f"l{i}"))
    await db.commit()
    await rollup_hourly(db)
    # delete the raw rows of the closed hour: counts must come from rollup
    for row in (
        (
            await db.execute(
                select(AlertEvent).where(AlertEvent.received_at < now - timedelta(hours=1))
            )
        )
        .scalars()
        .all()
    ):
        await db.delete(row)
    await db.commit()

    res = await client.get("/api/v1/stats/overview", headers=auth_headers(viewer))
    assert res.json()["data"]["alerts_24h"] == 7  # 5 rolled + 2 live

    res = await client.get("/api/v1/stats/trend?hours=24", headers=auth_headers(viewer))
    buckets = res.json()["data"]["buckets"]
    assert sum(b["critical"] for b in buckets) == 5
    assert sum(b["info"] for b in buckets) == 2


async def test_stats_rollups_tenant_isolated(client, db, tenant_a, tenant_b, a_viewer):
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    db.add(event(base, "critical", tenant_a.id, fp="ta"))
    db.add(event(base, "critical", tenant_b.id, fp="tb"))
    await db.commit()
    await rollup_hourly(db)
    await db.commit()

    res = await client.get("/api/v1/stats/overview", headers=auth_headers(a_viewer))
    assert res.json()["data"]["alerts_24h"] == 1  # only A's rollup row
