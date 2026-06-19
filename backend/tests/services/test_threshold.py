"""Threshold resolve + ingest-time filter. FAIL-OPEN is exhaustively covered:
missing cmdb_ci / no override / no catalog / no value_query / empty / query
error -> PASS (never suppress). Plus boundary, comparator direction, cache,
precedence (server>group>default, single group), tenancy."""

import uuid

from app.models.alerting import AlertEvent
from app.models.server import Server, ServerGroup
from app.models.threshold import RuleCatalog, ThresholdOverride
from app.services.threshold import (
    ValueCache,
    parse_instant_value,
    resolve_threshold,
    should_suppress,
)
from tests.notifications.helpers import NOW


def ev(name="HostOutOfMemory", cmdb="X", tenant_id=None):
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
        tenant_id=tenant_id,
    )


async def cat(
    db, name="HostOutOfMemory", comparator=">", vq='m{cmdb_ci="{{cmdb_ci}}"}', tenant_id=None
):
    db.add(
        RuleCatalog(
            alertname=name, comparator=comparator, unit="%", value_query=vq, tenant_id=tenant_id
        )
    )
    await db.flush()


async def ovr(
    db, name="HostOutOfMemory", tier="server", cmdb="X", group_id=None, value=95.0, tenant_id=None
):
    db.add(
        ThresholdOverride(
            alertname=name,
            tier=tier,
            target_cmdb_ci=(cmdb if tier == "server" else None),
            target_group_id=group_id,
            value=value,
            tenant_id=tenant_id,
        )
    )
    await db.flush()


def const_fetch(value, counter=None):
    async def f(_tid, _q):
        if counter is not None:
            counter.append(1)
        return value

    return f


def raising_fetch():
    async def f(_tid, _q):
        raise RuntimeError("mimir down")

    return f


# ---------- parse ----------
def test_parse_instant_value():
    assert parse_instant_value({"data": {"result": [{"value": [1, "92.5"]}]}}) == 92.5
    assert parse_instant_value({"data": {"result": []}}) is None
    assert parse_instant_value({"nope": 1}) is None
    assert parse_instant_value({"data": {"result": [{"value": [1, "NaNx"]}]}}) is None


# ---------- resolve precedence ----------
async def test_resolve_server_beats_group(db):
    g = ServerGroup(name="g")
    db.add(g)
    await db.flush()
    db.add(Server(name="X", cmdb_ci="X", server_group_id=g.id))
    await db.flush()
    await ovr(db, tier="group", group_id=g.id, value=80)
    await ovr(db, tier="server", cmdb="X", value=70)
    assert await resolve_threshold(db, None, "X", "HostOutOfMemory") == ("server", 70.0)


async def test_resolve_falls_to_group(db):
    g = ServerGroup(name="g")
    db.add(g)
    await db.flush()
    db.add(Server(name="X", cmdb_ci="X", server_group_id=g.id))
    await db.flush()
    await ovr(db, tier="group", group_id=g.id, value=80)
    assert await resolve_threshold(db, None, "X", "HostOutOfMemory") == ("group", 80.0)


async def test_resolve_default_none(db):
    assert await resolve_threshold(db, None, "X", "HostOutOfMemory") is None


async def test_resolve_tenant_isolated(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    await ovr(db, tier="server", cmdb="X", value=70, tenant_id=a)
    assert await resolve_threshold(db, b, "X", "HostOutOfMemory") is None  # B can't see A's


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
