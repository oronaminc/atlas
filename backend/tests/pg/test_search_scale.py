"""Feature B at scale on real PG (skipped without ATLAS_PG_TEST_URL): the
label search rides the GIN index (jsonb_path_ops) + partition pruning, no
seq scan. Mirrors the post-0006/0009 partitioned alert_events + GIN."""

import os
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base
from app.models.alerting import AlertEvent

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="ATLAS_PG_TEST_URL not set (run scripts/pg_concurrency_test.sh)"
)

NOW = datetime.now(UTC)


@pytest_asyncio.fixture
async def pg():
    schema = f"search_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(PG_URL, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        others = [t for t in Base.metadata.sorted_tables if t.name != "alert_events"]
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=others))
        ddl = str(CreateTable(AlertEvent.__table__).compile(dialect=postgresql.dialect()))
        ddl = ddl.replace("PRIMARY KEY (id)", "PRIMARY KEY (id, received_at)")
        ddl = ddl.rstrip().rstrip(")") + ") PARTITION BY RANGE (received_at)"
        await conn.execute(text(ddl))
        for index in AlertEvent.__table__.indexes:
            await conn.execute(text(str(CreateIndex(index).compile(dialect=postgresql.dialect()))))
        # the migration-0009 GIN index + daily partitions for the last week
        await conn.execute(
            text(
                "CREATE INDEX ix_alert_events_labels_gin ON alert_events "
                "USING gin (labels jsonb_path_ops)"
            )
        )
        for d in range(9):
            day = (NOW - timedelta(days=d)).strftime("%Y%m%d")
            lo = (NOW - timedelta(days=d)).strftime("%Y-%m-%d")
            hi = (NOW - timedelta(days=d - 1)).strftime("%Y-%m-%d")
            await conn.execute(
                text(
                    f"CREATE TABLE alert_events_p{day} PARTITION OF alert_events "
                    f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
                )
            )
        await conn.execute(
            text("CREATE TABLE alert_events_default PARTITION OF alert_events DEFAULT")
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await engine.dispose()


async def test_label_search_uses_gin_and_prunes_partitions(pg):
    async with pg() as db:
        # ~60k recent rows across hosts + an old partition that must be pruned
        await db.execute(
            text(
                "INSERT INTO alert_events (id,fingerprint,source,name,severity,status,labels,"
                "annotations,starts_at,received_at,dedup_count,created_at,updated_at) "
                "SELECT gen_random_uuid(),'fp'||g,'am','A','info','firing',"
                "jsonb_build_object('host','srv-'||(g%5000),'dc','seoul'),'{}'::jsonb,"
                "now()-(g%6||' days')::interval, now()-(g%6||' days')::interval,1,now(),now() "
                "FROM generate_series(1,60000) g"
            )
        )
        # one matching needle in the last day
        await db.execute(
            text(
                "INSERT INTO alert_events (id,fingerprint,source,name,severity,status,labels,"
                "annotations,starts_at,received_at,dedup_count,created_at,updated_at) VALUES "
                "(gen_random_uuid(),'needle','am','A','critical','firing',"
                "jsonb_build_object('host','needle-host'),'{}'::jsonb,now(),now(),1,now(),now())"
            )
        )
        await db.execute(text("ANALYZE alert_events"))
        await db.commit()

        old_part = f"alert_events_p{(NOW - timedelta(days=8)).strftime('%Y%m%d')}"
        plan = "\n".join(
            (
                await db.execute(
                    text(
                        "EXPLAIN SELECT id FROM alert_events "
                        "WHERE received_at >= now() - interval '7 days' "
                        'AND labels @> \'{"host":"needle-host"}\' '
                        "ORDER BY received_at DESC LIMIT 20"
                    )
                )
            ).scalars()
        )
        # GIN used: populated partitions go via Bitmap Index Scan on the GIN
        assert "Bitmap Index Scan" in plan and "_labels_idx" in plan, plan
        # no NON-TRIVIAL seq scan: empty partitions get a cost=0 0-row scan
        # (harmless); a real 60k-row full scan would have a high upper cost.
        for m in re.finditer(r"Seq Scan on \S+ \S+\s+\(cost=[\d.]+\.\.([\d.]+)", plan):
            assert float(m.group(1)) < 1.0, f"non-trivial seq scan:\n{plan}"
        assert old_part not in plan, plan  # 8-day-old partition pruned
