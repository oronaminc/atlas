"""Partition mechanics against real PostgreSQL (skipped without
ATLAS_PG_TEST_URL): pruning EXPLAIN assertions, DEFAULT-partition safety +
re-homing, retention drop + archive. The populated-table MIGRATION proof
(10M rows, zero loss, lock window) is a harness procedure — see the
load-test skill + CLAUDE.md Phase 3 findings."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base
from app.models.alerting import AlertEvent
from app.services import maintenance as mt

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="ATLAS_PG_TEST_URL not set (run scripts/pg_concurrency_test.sh)"
)

NOW = datetime.now(UTC)


@pytest_asyncio.fixture
async def pg(monkeypatch):
    schema = f"part_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(PG_URL, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        # everything except alert_events from metadata...
        others = [t for t in Base.metadata.sorted_tables if t.name != "alert_events"]
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=others))
        # ...then alert_events as the post-0006 partitioned parent
        ddl = str(CreateTable(AlertEvent.__table__).compile(dialect=postgresql.dialect()))
        ddl = ddl.replace("PRIMARY KEY (id)", "PRIMARY KEY (id, received_at)")
        ddl = ddl.rstrip().rstrip(")") + ") PARTITION BY RANGE (received_at)"
        # CreateTable wraps cols in parens; safe textual surgery verified below
        await conn.execute(text(ddl))
        for index in AlertEvent.__table__.indexes:
            await conn.execute(text(str(CreateIndex(index).compile(dialect=postgresql.dialect()))))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await engine.dispose()


def make_event(received_at, fp="fp-1"):
    return AlertEvent(
        fingerprint=fp,
        source="alertmanager",
        name="A",
        severity="warning",
        status="firing",
        labels={},
        annotations={},
        starts_at=received_at,
        received_at=received_at,
    )


async def make_day_partition(db, day):
    await db.execute(
        text(
            f"CREATE TABLE {mt.partition_name(day)} PARTITION OF alert_events "
            f"FOR VALUES FROM ('{day:%Y-%m-%d}') TO ('{day + timedelta(days=1):%Y-%m-%d}')"
        )
    )


async def test_insert_never_fails_and_default_rehomes(pg):
    async with pg() as db:
        created = await mt.ensure_partitions(db, days_ahead=1)
        assert created >= 2  # today, tomorrow, DEFAULT

        # a date with NO partition (e.g. worker down for a week): must land
        # in DEFAULT instead of failing
        stray_day = NOW + timedelta(days=30)
        db.add(make_event(stray_day, fp="stray"))
        await db.commit()
        assert await mt.default_partition_count(db) == 1

        rehomed = await mt.rehome_default_rows(db)
        await db.commit()
        assert rehomed == 1
        assert await mt.default_partition_count(db) == 0
        assert mt.partition_name(stray_day) in await mt.list_partitions(db)
        # row survived the move and is queryable through the parent
        count = (
            await db.execute(
                select(func.count())
                .select_from(AlertEvent)
                .where(AlertEvent.fingerprint == "stray")
            )
        ).scalar_one()
        assert count == 1


async def test_partition_pruning_on_hot_queries(pg):
    async with pg() as db:
        await mt.ensure_partitions(db, days_ahead=0)
        old_day = (NOW - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        await make_day_partition(db, old_day)
        db.add(make_event(NOW, fp="fresh"))
        db.add(make_event(old_day + timedelta(hours=1), fp="old"))
        await db.commit()

        old_name = mt.partition_name(old_day)

        # dedup lookup (engine._latest_other_event shape): window-bounded
        plan = "\n".join(
            (
                await db.execute(
                    text(
                        "EXPLAIN SELECT id FROM alert_events WHERE fingerprint = 'fresh' "
                        "AND received_at >= now() - interval '300 seconds' "
                        "ORDER BY received_at DESC LIMIT 1"
                    )
                )
            ).scalars()
        )
        assert old_name not in plan, plan

        # claim scan (correlation_worker shape): lookback-bounded
        plan = "\n".join(
            (
                await db.execute(
                    text(
                        "EXPLAIN SELECT id FROM alert_events WHERE incident_id IS NULL "
                        "AND (claimed_at IS NULL OR claimed_at < now() - interval '60 seconds') "
                        "AND received_at >= now() - interval '7 days' "
                        "ORDER BY received_at ASC LIMIT 100"
                    )
                )
            ).scalars()
        )
        assert old_name not in plan, plan

        # stats live tail: current-hour scan
        plan = "\n".join(
            (
                await db.execute(
                    text(
                        "EXPLAIN SELECT received_at, severity FROM alert_events "
                        "WHERE received_at >= date_trunc('hour', now())"
                    )
                )
            ).scalars()
        )
        assert old_name not in plan, plan


async def test_retention_drops_expired_partition_and_archives(pg, tmp_path, monkeypatch):
    monkeypatch.setattr(mt.settings, "ARCHIVE_DIR", str(tmp_path))
    async with pg() as db:
        await mt.ensure_partitions(db, days_ahead=0)
        old_day = (NOW - timedelta(days=120)).replace(hour=0, minute=0, second=0, microsecond=0)
        recent_day = (NOW - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        await make_day_partition(db, old_day)
        await make_day_partition(db, recent_day)
        db.add(make_event(old_day + timedelta(hours=3), fp="ancient"))
        db.add(make_event(recent_day + timedelta(hours=3), fp="recent"))
        await db.commit()

        config = await mt.get_retention_config(db)
        config.archive_enabled = True
        await db.commit()

        dropped = await mt.drop_expired_partitions(db, retention_days=90)
        await db.commit()
        assert dropped == [mt.partition_name(old_day)]
        # archive written with the expired row
        archive = tmp_path / f"{mt.partition_name(old_day)}.csv.gz"
        assert archive.exists()
        import gzip

        content = gzip.open(archive, "rt").read()
        assert "ancient" in content

        # recent data untouched; expired rows gone
        fps = [r for r in (await db.execute(select(AlertEvent.fingerprint))).scalars()]
        assert fps == ["recent"]
