"""Phase 5 observability: /metrics exposition format + value correctness,
cardinality bound, soft-cap breach gauge, worker health/readiness, the
zero-dep registry primitives."""

from datetime import UTC, datetime

import app.core.instruments as m
from app.api.v1.metrics import collect_db_gauges
from app.core.config import settings
from app.core.metrics import Counter, Gauge, Registry
from app.models.alerting import AlertEvent, Incident, IncidentStatus
from app.models.delivery import Notification
from app.models.user import GlobalRole
from tests.conftest import make_user

# --- registry primitives ---


def test_registry_renders_prometheus_004():
    reg = Registry()
    c = reg.counter("atlas_test_total", "doc", ("label",))
    g = reg.gauge("atlas_test_gauge", "doc")
    h = reg.histogram("atlas_test_seconds", "doc", buckets=(0.1, 1.0))
    c.inc(label="x")
    c.inc(2, label="x")
    g.set(5)
    h.observe(0.05)
    h.observe(0.5)
    out = reg.render()
    assert "# TYPE atlas_test_total counter" in out
    assert 'atlas_test_total{label="x"} 3' in out
    assert "atlas_test_gauge 5" in out
    assert "# TYPE atlas_test_seconds histogram" in out
    assert 'atlas_test_seconds_bucket{le="0.1"} 1' in out
    assert 'atlas_test_seconds_bucket{le="+Inf"} 2' in out
    assert "atlas_test_seconds_count 2" in out
    # every line is `name value` or a comment (valid exposition)
    for line in out.splitlines():
        assert line.startswith("#") or len(line.rsplit(" ", 1)) == 2


def test_counter_label_escaping():
    reg = Registry()
    c = reg.counter("atlas_x_total", "d", ("svc",))
    c.inc(svc='a"b\\c')
    assert 'svc="a\\"b\\\\c"' in reg.render()


# --- API /metrics endpoint ---


async def test_api_metrics_endpoint_exposes_instruments(client):
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain; version=0.0.4")
    body = res.text
    for name in (
        "atlas_ingest_requests_total",
        "atlas_notifications_pending",
        "atlas_default_partition_rows",
        "atlas_correlation_backlog",
        "atlas_alert_stats_rollup_lag_seconds",
    ):
        assert f"# TYPE {name}" in body


async def test_ingest_increments_counter(client, db):
    before = _counter_val(m.ingest_events, provider="alertmanager")
    res = await client.post(
        "/api/v1/ingest/alertmanager",
        json={"alerts": [{"status": "firing", "labels": {"alertname": "X", "host": "h"}}]},
        headers={"X-Atlas-Ingest-Key": "test-ingest-key"},
    )
    assert res.status_code == 202
    assert _counter_val(m.ingest_events, provider="alertmanager") == before + 1


# --- DB-derived gauges ---


async def test_queue_depth_gauge_rises_with_backlog(db):
    user_incident = Incident(
        title="i",
        status=IncidentStatus.open,
        severity="critical",
        group_key="h",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        alert_count=1,
    )
    db.add(user_incident)
    await db.flush()
    for i in range(7):
        u = await make_user(db, f"q{i}@x.io", GlobalRole.viewer)
        db.add(
            Notification(
                incident_id=user_incident.id,
                channel="telegram",
                recipient_user_id=u.id,
                recipient_address=f"c{i}",
                status="pending",
            )
        )
    # uncorrelated alert events -> correlation backlog
    for i in range(3):
        db.add(
            AlertEvent(
                fingerprint=f"f{i}",
                source="am",
                name="A",
                severity="info",
                status="firing",
                labels={},
                annotations={},
                starts_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )
        )
    await db.commit()

    await collect_db_gauges(db)
    assert _gauge_val(m.notifications_pending) == 7
    assert _gauge_val(m.correlation_backlog) == 3
    assert _gauge_val(m.notifications_oldest_pending_seconds) >= 0


async def test_softcap_breach_is_breach_only_global(db, monkeypatch):
    # global pending exceeds the (env) cap -> exactly one series, service="global".
    monkeypatch.setattr(settings, "NOTIFY_PENDING_SOFTCAP", 3)
    inc = Incident(
        title="a",
        status=IncidentStatus.open,
        severity="critical",
        group_key="h",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        alert_count=1,
    )
    db.add(inc)
    await db.flush()
    for i in range(5):  # 5 > cap 3
        u = await make_user(db, f"sa{i}@x.io", GlobalRole.viewer)
        db.add(
            Notification(
                incident_id=inc.id,
                channel="telegram",
                recipient_user_id=u.id,
                recipient_address=f"a{i}",
                status="pending",
            )
        )
    await db.commit()

    await collect_db_gauges(db)
    series = dict(_gauge_series(m.tenant_pending_softcap_breached))
    assert series == {("global",): 1}  # single global breach series


async def test_softcap_clears_when_resolved(db, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_PENDING_SOFTCAP", 100000)
    await collect_db_gauges(db)
    # no breach -> zero series (cardinality bound in steady state)
    assert list(_gauge_series(m.tenant_pending_softcap_breached)) == []


# --- helpers ---


def _counter_val(counter: Counter, **labels) -> float:
    key = counter._key(labels)
    return counter._values.get(key, 0.0)


def _gauge_val(gauge: Gauge) -> float:
    for _labels, v in gauge.samples():
        return v
    return 0.0


def _gauge_series(gauge: Gauge):
    return [(tuple(labels.values()), v) for labels, v in gauge.samples()]
