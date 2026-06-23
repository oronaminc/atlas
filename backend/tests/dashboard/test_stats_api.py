"""Dashboard aggregation endpoints: counts, trend buckets (hour-aligned),
per-server fold (by cmdb_hostname), permissions (any auth; 401 without token)."""

from datetime import timedelta

from app.models.alerting import AlertEvent, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import Notification
from tests.notifications.helpers import seed_incident, seed_user


async def seed_dashboard_data(db):
    now = utcnow()
    open_critical = await seed_incident(db, severity="critical", title="db-01 down")
    open_warning = await seed_incident(db, severity="warning", title="web-01 slow")
    resolved = await seed_incident(db, severity="info", title="resolved one")
    resolved.status = IncidentStatus.resolved

    for status, sent_offset in (("sent", -1), ("failed", None), ("pending", None)):
        user = await seed_user(db, f"rcpt-{status}@example.com", chat_id="1")
        db.add(
            Notification(
                incident_id=open_critical.id,
                channel="telegram",
                recipient_user_id=user.id,
                recipient_address=str(status),
                group_id=None,
                status=status,
                sent_at=now + timedelta(hours=sent_offset) if sent_offset else None,
                last_error="boom" if status == "failed" else None,
            )
        )

    # alert events in/out of the 24h window, denormalized cmdb_hostname + attached
    for hours_ago, severity, host, inc in (
        (1, "critical", "db-01", open_critical),
        (2, "warning", "web-01", open_warning),
        (30, "info", "web-01", resolved),
    ):
        db.add(
            AlertEvent(
                fingerprint=f"f{hours_ago}",
                source="alertmanager",
                name=f"A{hours_ago}",
                severity=severity,
                status="firing",
                labels={"cmdb_hostname": host},
                annotations={},
                starts_at=now - timedelta(hours=hours_ago),
                received_at=now - timedelta(hours=hours_ago),
                cmdb_hostname=host,
                cmdb_service_l2_code="L2TEST",  # visible to non-admin viewer (IMP)
                incident_id=inc.id,
            )
        )
    await db.commit()
    return open_critical


async def test_overview_counts(client, db, viewer_headers):
    await seed_dashboard_data(db)
    data = (await client.get("/api/v1/stats/overview", headers=viewer_headers)).json()["data"]
    assert data["incidents"]["open"] == 2
    assert data["incidents"]["resolved"] == 1
    assert data["open_by_severity"]["critical"] == 1
    assert data["alerts_24h"] == 2  # 1h + 2h; 30h excluded


async def test_trend_buckets(client, db, viewer_headers):
    await seed_dashboard_data(db)
    data = (await client.get("/api/v1/stats/trend?hours=24", headers=viewer_headers)).json()["data"]
    assert data["bucket_seconds"] == 3600
    assert len(data["buckets"]) in (24, 25)  # hour-aligned window incl. current bucket
    totals = {s: sum(b[s] for b in data["buckets"]) for s in ("critical", "warning", "info")}
    assert totals["critical"] == 1 and totals["warning"] == 1  # both in-window

    data = (await client.get("/api/v1/stats/trend?hours=168", headers=viewer_headers)).json()[
        "data"
    ]
    assert data["bucket_seconds"] == 86400
    assert len(data["buckets"]) in (7, 8)
    assert sum(b["info"] for b in data["buckets"]) == 1  # the 30h-old event


async def test_hosts_per_server(client, db, viewer_headers):
    await seed_dashboard_data(db)
    rows = {
        r["host"]: r
        for r in (await client.get("/api/v1/stats/hosts", headers=viewer_headers)).json()["data"]
    }
    assert "db-01" in rows and "web-01" in rows
    assert rows["db-01"]["max_severity"] == "critical"
    assert rows["db-01"]["open"] == 1 and rows["db-01"]["total"] == 1
    assert rows["db-01"]["alerts"] == 1


async def test_suppressed_excluded_from_active_stats(client, db, viewer_headers):
    await seed_dashboard_data(db)
    muted = await seed_incident(db, severity="critical", title="muted on db-01")
    muted.status = IncidentStatus.suppressed
    await db.commit()
    data = (await client.get("/api/v1/stats/overview", headers=viewer_headers)).json()["data"]
    assert data["open_by_severity"]["critical"] == 1  # muted critical NOT counted


async def test_stats_require_auth(client):
    for path in ("/api/v1/stats/overview", "/api/v1/stats/trend", "/api/v1/stats/hosts"):
        assert (await client.get(path)).status_code == 401
