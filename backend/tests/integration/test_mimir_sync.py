"""Mimir read-cache sync: rules + silences pulled into atlas, idempotent,
base-threshold extraction from rule labels/annotations (no PromQL)."""

import pytest
from sqlalchemy import func, select

from app.models.mimir import MimirRule, MimirSilence
from app.services.mimir_sync import extract_threshold, sync_rules, sync_silences

pytestmark = pytest.mark.asyncio


class FakeQuery:
    def __init__(self, rules):
        self._rules = rules

    async def alerting_rules(self):
        return self._rules


class FakeAM:
    def __init__(self, silences):
        self._s = silences

    async def get_silences(self):
        return self._s


RULES = [
    {
        "_namespace": "ns1",
        "_group": "cpu",
        "name": "HighCPU",
        "type": "alerting",
        "query": "cpu > 80",
        "duration": 300,
        "labels": {"severity": "warning", "atlas_threshold": "80", "atlas_compare": ">"},
        "annotations": {"summary": "cpu high"},
        "health": "ok",
        "state": "firing",
        "lastError": "",
        "lastEvaluation": "2026-06-22T12:00:00Z",
        "alerts": [{"value": "83"}, {"value": "70"}],
    },
    {
        "_namespace": "ns1",
        "_group": "mem",
        "name": "BrokenRule",
        "type": "alerting",
        "query": "mem",
        "duration": 60,
        "labels": {"severity": "critical"},
        "annotations": {},
        "health": "err",
        "state": "inactive",
        "lastError": "parse error: bad query",
        "lastEvaluation": "2026-06-22T12:00:00Z",
        "alerts": [],
    },
]

SILENCES = [
    {
        "id": "sil-1",
        "status": {"state": "active"},
        "matchers": [{"name": "cmdb_service_l2_code", "value": "PAY-L2", "isRegex": False}],
        "startsAt": "2026-06-22T10:00:00Z",
        "endsAt": "2026-06-22T14:00:00Z",
        "createdBy": "admin",
        "comment": "maintenance",
    }
]


def test_extract_threshold_annotation_wins():
    base, cmp = extract_threshold(
        {"atlas_threshold": "80", "atlas_compare": "<"},
        {"atlas_threshold": "90", "atlas_compare": ">"},
    )
    assert base == 90.0 and cmp == ">"


def test_extract_threshold_absent_fail_open():
    assert extract_threshold({}, {}) == (None, None)


async def test_sync_rules_caches_state_and_base(db):
    n = await sync_rules(db, FakeQuery(RULES))
    await db.commit()
    assert n == 2
    high = (
        await db.execute(select(MimirRule).where(MimirRule.alertname == "HighCPU"))
    ).scalar_one()
    assert high.base_threshold == 80.0
    assert high.comparator == ">"
    assert high.value == 83.0  # max over active alert values
    assert high.health == "ok" and high.state == "firing"
    assert high.for_seconds == 300
    broken = (
        await db.execute(select(MimirRule).where(MimirRule.alertname == "BrokenRule"))
    ).scalar_one()
    assert broken.last_error == "parse error: bad query"  # eval error surfaced
    assert broken.base_threshold is None  # no atlas_threshold -> fail-open base


async def test_sync_rules_idempotent(db):
    await sync_rules(db, FakeQuery(RULES))
    await db.commit()
    await sync_rules(db, FakeQuery(RULES))
    await db.commit()
    assert (await db.execute(select(func.count()).select_from(MimirRule))).scalar_one() == 2


async def test_sync_silences(db):
    n = await sync_silences(db, FakeAM(SILENCES))
    await db.commit()
    assert n == 1
    row = (await db.execute(select(MimirSilence))).scalar_one()
    assert row.silence_id == "sil-1"
    assert row.state == "active"
    assert row.matchers[0]["name"] == "cmdb_service_l2_code"
    # idempotent
    await sync_silences(db, FakeAM(SILENCES))
    await db.commit()
    assert (await db.execute(select(func.count()).select_from(MimirSilence))).scalar_one() == 1
