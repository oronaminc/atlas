"""Dashboard aggregation endpoints: counts, trend buckets, per-host fold,
permissions (any authenticated user; 401 without token)."""

from datetime import timedelta

from app.models.alerting import AlertEvent, IncidentStatus
from app.models.base import utcnow
from app.models.delivery import Notification
from tests.notifications.helpers import seed_incident, seed_user


async def seed_dashboard_data(db):
    now = utcnow()
    open_critical = await seed_incident(db, severity="critical", title="db-01 down")
    open_critical.group_key = "host=db-01"
    open_warning = await seed_incident(db, severity="warning", title="web-01 slow")
    open_warning.group_key = "host=web-01"
    resolved = await seed_incident(db, severity="info", title="resolved one")
    resolved.group_key = "host=web-01"
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

    # alert events inside / outside the 24h window
    for hours_ago, severity in ((1, "critical"), (2, "warning"), (30, "info")):
        db.add(
            AlertEvent(
                fingerprint=f"f{hours_ago}",
                source="alertmanager",
                name=f"A{hours_ago}",
                severity=severity,
                status="firing",
                labels={"host": "db-01"},
                annotations={},
                starts_at=now - timedelta(hours=hours_ago),
                received_at=now - timedelta(hours=hours_ago),
            )
        )
    await db.commit()
    return open_critical


async def test_overview_counts(client, db, viewer_headers):
    await seed_dashboard_data(db)
    res = await client.get("/api/v1/stats/overview", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["incidents"]["open"] == 2
    assert data["incidents"]["resolved"] == 1
    assert data["open_by_severity"]["critical"] == 1
    assert data["open_by_severity"]["warning"] == 1
    assert data["notifications"]["sent"] == 1
    assert data["notifications"]["failed"] == 1
    assert data["notifications"]["pending"] == 1
    assert data["alerts_24h"] == 2  # the 30h-old event is excluded


async def test_trend_buckets(client, db, viewer_headers):
    await seed_dashboard_data(db)
    res = await client.get("/api/v1/stats/trend?hours=24", headers=viewer_headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["bucket_seconds"] == 3600
    assert len(data["buckets"]) == 24
    totals = {s: sum(b[s] for b in data["buckets"]) for s in ("critical", "warning", "info")}
    assert totals == {"critical": 1, "warning": 1, "info": 0}

    # 7d window -> daily buckets, includes the 30h-old event
    res = await client.get("/api/v1/stats/trend?hours=168", headers=viewer_headers)
    data = res.json()["data"]
    assert data["bucket_seconds"] == 86400
    assert len(data["buckets"]) == 7
    assert sum(b["info"] for b in data["buckets"]) == 1


async def test_hosts_aggregation(client, db, viewer_headers):
    await seed_dashboard_data(db)
    res = await client.get("/api/v1/stats/hosts", headers=viewer_headers)
    assert res.status_code == 200
    rows = {r["group_key"]: r for r in res.json()["data"]}
    assert rows["host=db-01"]["open"] == 1
    assert rows["host=db-01"]["max_severity"] == "critical"
    assert rows["host=web-01"]["open"] == 1
    assert rows["host=web-01"]["total"] == 2  # one open + one resolved
    # ordering: most open first, then noisiest
    keys = [r["group_key"] for r in res.json()["data"]]
    assert set(keys) == {"host=db-01", "host=web-01"}


async def test_stats_require_auth(client):
    for path in (
        "/api/v1/stats/overview",
        "/api/v1/stats/trend",
        "/api/v1/stats/hosts",
    ):
        assert (await client.get(path)).status_code == 401
