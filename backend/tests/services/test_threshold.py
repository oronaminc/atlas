"""Threshold resolve + ingest-time filter. FAIL-OPEN is exhaustively covered:
missing cmdb_ci / no override / no catalog / no value_query / empty / query
error -> PASS (never suppress). Plus boundary, comparator direction, cache,
precedence (cmdb_ci > label > default)."""

from app.models.alerting import AlertEvent
from app.models.threshold import RuleCatalog, ThresholdOverride
from app.services.threshold import (
    ValueCache,
    parse_instant_value,
    resolve_threshold,
    should_suppress,
)
from tests.notifications.helpers import NOW


def ev(name="HostOutOfMemory", cmdb="X"):
    return AlertEvent(
        fingerprint="fp",
        source="am",
        name=name,
        severity="critical",
        status="firing",
        labels=({"cmdb_ci": cmdb} if cmdb else {}),
        annotations={},
        starts_at=NOW,
        received_at=NOW,
    )


async def cat(db, name="HostOutOfMemory", comparator=">", vq='m{cmdb_ci="{{cmdb_ci}}"}'):
    db.add(RuleCatalog(alertname=name, comparator=comparator, unit="%", value_query=vq))
    await db.flush()


async def ovr(
    db,
    name="HostOutOfMemory",
    cmdb="X",
    label_key=None,
    label_value=None,
    value=95.0,
):
    db.add(
        ThresholdOverride(
            alertname=name,
            target_cmdb_ci=(cmdb if label_key is None else None),
            target_label_key=label_key,
            target_label_value=label_value,
            value=value,
        )
    )
    await db.flush()


def const_fetch(value, counter=None):
    async def f(_q):
        if counter is not None:
            counter.append(1)
        return value

    return f


def raising_fetch():
    async def f(_q):
        raise RuntimeError("mimir down")

    return f


# ---------- parse ----------
def test_parse_instant_value():
    assert parse_instant_value({"data": {"result": [{"value": [1, "92.5"]}]}}) == 92.5
    assert parse_instant_value({"data": {"result": []}}) is None
    assert parse_instant_value({"nope": 1}) is None
    assert parse_instant_value({"data": {"result": [{"value": [1, "NaNx"]}]}}) is None


# ---------- resolve precedence (label-based: cmdb_ci > label > none) ----------
LBL = {"cmdb_ci": "X", "cmdb_service_l2_code": "L2"}


async def test_resolve_cmdb_beats_label(db):
    await ovr(db, label_key="cmdb_service_l2_code", label_value="L2", value=80)
    await ovr(db, cmdb="X", value=70)
    assert await resolve_threshold(db, LBL, "HostOutOfMemory") == ("cmdb_ci", 70.0)


async def test_resolve_falls_to_label(db):
    await ovr(db, label_key="cmdb_service_l2_code", label_value="L2", value=80)
    assert await resolve_threshold(db, LBL, "HostOutOfMemory") == ("label", 80.0)


async def test_resolve_label_value_must_match(db):
    await ovr(db, label_key="cmdb_service_l2_code", label_value="OTHER", value=80)
    assert await resolve_threshold(db, LBL, "HostOutOfMemory") is None


async def test_resolve_default_none(db):
    assert await resolve_threshold(db, LBL, "HostOutOfMemory") is None


# ---------- suppress (gt) ----------
async def test_gt_suppress_below_threshold(db):
    await cat(db, comparator=">")
    await ovr(db, value=95)
    s, v = await should_suppress(db, ev(), fetch_value=const_fetch(92.0), cache=ValueCache())
    assert s is True and v == 92.0


async def test_gt_at_threshold_not_suppressed(db):
    await cat(db, comparator=">")
    await ovr(db, value=95)
    s, v = await should_suppress(db, ev(), fetch_value=const_fetch(95.0), cache=ValueCache())
    assert s is False and v == 95.0


async def test_gt_above_threshold_not_suppressed(db):
    await cat(db, comparator=">")
    await ovr(db, value=95)
    s, _ = await should_suppress(db, ev(), fetch_value=const_fetch(97.0), cache=ValueCache())
    assert s is False


# ---------- suppress (lt) ----------
async def test_lt_suppress_above_threshold(db):
    await cat(db, comparator="<")
    await ovr(db, value=10)
    s, _ = await should_suppress(db, ev(), fetch_value=const_fetch(20.0), cache=ValueCache())
    assert s is True  # mem-available 20 > 10 -> not severe -> suppress


async def test_lt_below_threshold_not_suppressed(db):
    await cat(db, comparator="<")
    await ovr(db, value=10)
    s, _ = await should_suppress(db, ev(), fetch_value=const_fetch(5.0), cache=ValueCache())
    assert s is False


# ---------- FAIL-OPEN ----------
async def test_failopen_no_override_no_query(db):
    await cat(db)  # catalog exists but no override
    counter: list = []
    s, v = await should_suppress(
        db, ev(), fetch_value=const_fetch(1.0, counter), cache=ValueCache()
    )
    assert s is False and v is None and counter == []  # never queried


async def test_failopen_missing_cmdb_ci(db):
    await cat(db)
    await ovr(db, value=95)
    s, _ = await should_suppress(db, ev(cmdb=None), fetch_value=raising_fetch(), cache=ValueCache())
    assert s is False


async def test_failopen_no_catalog(db):
    await ovr(db, value=95)  # override but no catalog row
    s, _ = await should_suppress(db, ev(), fetch_value=raising_fetch(), cache=ValueCache())
    assert s is False


async def test_failopen_no_value_query(db):
    await cat(db, vq=None)
    await ovr(db, value=95)
    s, _ = await should_suppress(db, ev(), fetch_value=raising_fetch(), cache=ValueCache())
    assert s is False


async def test_failopen_empty_value(db):
    await cat(db)
    await ovr(db, value=95)
    s, v = await should_suppress(db, ev(), fetch_value=const_fetch(None), cache=ValueCache())
    assert s is False and v is None


async def test_failopen_query_raises(db):
    await cat(db)
    await ovr(db, value=95)
    s, v = await should_suppress(db, ev(), fetch_value=raising_fetch(), cache=ValueCache())
    assert s is False and v is None  # exception swallowed -> PASS


# ---------- cache ----------
async def test_cache_single_query_for_repeats(db):
    await cat(db)
    await ovr(db, value=95)
    counter: list = []
    cache = ValueCache()
    f = const_fetch(92.0, counter)
    s1, _ = await should_suppress(db, ev(), fetch_value=f, cache=cache, now=100.0)
    s2, _ = await should_suppress(db, ev(), fetch_value=f, cache=cache, now=101.0)
    assert s1 is True and s2 is True
    assert len(counter) == 1  # second call served from cache
