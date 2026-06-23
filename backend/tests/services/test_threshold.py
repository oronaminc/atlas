"""Ingest threshold filter (no PromQL): suppress iff the alert's carried value
is below the effective threshold (per-server cmdb_ci > per-service label > rule
base). Base+comparator from the alert's annotations, else the cached Mimir rule.
Fail-open everywhere."""

import pytest

from app.models.alerting import AlertEvent
from app.models.base import utcnow
from app.models.mimir import MimirRule
from app.models.threshold import ThresholdOverride
from app.services.threshold import should_suppress, value_from_annotations

pytestmark = pytest.mark.asyncio

NOW = utcnow()


def ev(*, value=None, labels=None, annotations=None, name="HighCPU") -> AlertEvent:
    return AlertEvent(
        fingerprint="fp",
        source="alertmanager",
        name=name,
        severity="warning",
        status="firing",
        labels=labels if labels is not None else {"cmdb_ci": "CI-1"},
        annotations=annotations or {},
        starts_at=NOW,
        received_at=NOW,
        value=value,
    )


async def _cache_rule(db, name="HighCPU", base=80.0, comparator=">"):
    db.add(
        MimirRule(
            alertname=name,
            base_threshold=base,
            comparator=comparator,
            labels={},
            annotations={},
            synced_at=NOW,
        )
    )
    await db.flush()


def test_value_from_annotations():
    assert value_from_annotations({"value": "83.5"}) == 83.5
    assert value_from_annotations({}) is None


async def test_base_from_alert_annotations_fires_when_above(db):
    e = ev(value=83.0, annotations={"atlas_threshold": "80", "atlas_compare": ">"})
    s, v = await should_suppress(db, e)
    assert s is False and v == 83.0  # 83 > 80 -> incident-worthy


async def test_base_from_alert_annotations_suppress_when_below(db):
    e = ev(value=70.0, annotations={"atlas_threshold": "80", "atlas_compare": ">"})
    s, _ = await should_suppress(db, e)
    assert s is True  # 70 < 80 -> not incident-worthy


async def test_per_server_override_beats_base(db):
    # rule base 80; CPU-heavy server overrides to 90; value 83 -> suppress
    await _cache_rule(db)
    db.add(ThresholdOverride(alertname="HighCPU", target_cmdb_ci="CI-1", value=90.0))
    await db.flush()
    s, _ = await should_suppress(db, ev(value=83.0))
    assert s is True


async def test_per_service_override(db):
    await _cache_rule(db)
    db.add(
        ThresholdOverride(
            alertname="HighCPU",
            target_label_key="cmdb_service_l2_code",
            target_label_value="PAY-L2",
            value=95.0,
        )
    )
    await db.flush()
    e = ev(value=90.0, labels={"cmdb_ci": "CI-9", "cmdb_service_l2_code": "PAY-L2"})
    s, _ = await should_suppress(db, e)
    assert s is True  # 90 < 95


async def test_per_server_beats_per_service(db):
    await _cache_rule(db)
    db.add_all(
        [
            ThresholdOverride(
                alertname="HighCPU",
                target_label_key="cmdb_service_l2_code",
                target_label_value="PAY-L2",
                value=95.0,
            ),
            ThresholdOverride(alertname="HighCPU", target_cmdb_ci="CI-1", value=70.0),
        ]
    )
    await db.flush()
    # value 80: below service(95) but above server(70). server wins -> NOT suppressed
    e = ev(value=80.0, labels={"cmdb_ci": "CI-1", "cmdb_service_l2_code": "PAY-L2"})
    s, _ = await should_suppress(db, e)
    assert s is False


async def test_base_from_cached_rule(db):
    await _cache_rule(db, base=80.0, comparator=">")
    s, _ = await should_suppress(db, ev(value=75.0))  # no alert annotations
    assert s is True  # 75 < cached 80


async def test_lt_comparator(db):
    # mem-available rule fires LOW; suppress when value is HIGH (healthy)
    e = ev(value=40.0, annotations={"atlas_threshold": "20", "atlas_compare": "<"})
    s, _ = await should_suppress(db, e)
    assert s is True  # 40 > 20 -> healthy -> not incident-worthy


async def test_failopen_no_value(db):
    e = ev(value=None, annotations={"atlas_threshold": "80", "atlas_compare": ">"})
    s, v = await should_suppress(db, e)
    assert s is False and v is None


async def test_failopen_no_comparator(db):
    s, v = await should_suppress(db, ev(value=50.0))
    assert s is False and v == 50.0
