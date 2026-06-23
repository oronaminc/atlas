"""Phase 4 claim path against real PostgreSQL (skipped without
ATLAS_PG_TEST_URL): the partial claim index turns the 861ms seq-scan+sort into
an index-ordered scan. Multi-tenancy is removed, so the claim is a single
global queue ordered by (priority, created_at)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base

PG_URL = os.environ.get("ATLAS_PG_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="ATLAS_PG_TEST_URL not set (run scripts/pg_concurrency_test.sh)"
)

NOW = datetime.now(UTC)


@pytest_asyncio.fixture
async def pg():
    schema = f"notif_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(PG_URL, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.run_sync(Base.metadata.create_all)
        # replace the plain metadata index with the partial one the baseline
        # migration creates, so the test exercises the real production index
        await conn.execute(text("DROP INDEX ix_notifications_claim"))
        await conn.execute(
            text(
                "CREATE INDEX ix_notifications_claim ON notifications "
                "(priority, created_at) WHERE status IN ('pending','failed')"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, schema
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await engine.dispose()


async def _seed_incident(db) -> uuid.UUID:
    inc = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO incidents (id,title,status,severity,group_key,first_seen,"
            "last_seen,alert_count,created_at,updated_at) VALUES "
            "(:id,'x','open','warning','h',now(),now(),1,now(),now())"
        ),
        {"id": inc},
    )
    return inc


async def test_claim_uses_partial_index_no_seqscan_no_sort(pg):
    factory, schema = pg
    async with factory() as db:
        inc = await _seed_incident(db)
        # blow up to ~300k claimable (one row per user)
        await db.execute(
            text(
                "INSERT INTO users (id,email,username,role,auth_provider,is_active,"
                "created_at,updated_at) SELECT gen_random_uuid(),'bulk'||g||'@x.io','bulk'||g,"
                "'viewer','local',true,now(),now() FROM generate_series(1,300000) g"
            ),
            {},
        )
        await db.execute(
            text(
                "INSERT INTO notifications (id,incident_id,channel,recipient_user_id,"
                "recipient_address,status,attempts,priority,created_at,updated_at) "
                "SELECT gen_random_uuid(), :inc, 'telegram', u.id, u.id::text,'pending',0,1,"
                "now(),now() FROM users u WHERE u.username LIKE 'bulk%'"
            ),
            {"inc": inc},
        )
        await db.execute(text("ANALYZE notifications"))
        await db.commit()

        plan = "\n".join(
            (
                await db.execute(
                    text(
                        "EXPLAIN SELECT id FROM notifications "
                        "WHERE status IN ('pending','failed') "
                        "AND (retry_at IS NULL OR retry_at <= now()) "
                        "AND (claimed_at IS NULL OR claimed_at < now() - interval '60 seconds') "
                        "ORDER BY priority, created_at LIMIT 25 FOR UPDATE SKIP LOCKED"
                    )
                )
            ).scalars()
        )
        assert "ix_notifications_claim" in plan, plan
        assert "Seq Scan" not in plan, plan
        assert "Sort" not in plan, plan


async def test_claim_batch_index_backed_at_scale(pg):
    factory, schema = pg
    from app.notifications.outbox import claim_batch

    async with factory() as db:
        inc = await _seed_incident(db)
        # 50k pending in a single global queue
        await db.execute(
            text(
                "INSERT INTO users (id,email,username,role,auth_provider,is_active,"
                "created_at,updated_at) SELECT gen_random_uuid(),'z'||g||'@x.io','z'||g,"
                "'viewer','local',true,now(),now() FROM generate_series(1,50000) g"
            ),
            {},
        )
        await db.execute(
            text(
                "INSERT INTO notifications (id,incident_id,channel,recipient_user_id,"
                "recipient_address,status,attempts,priority,created_at,updated_at) "
                "SELECT gen_random_uuid(), :inc,'telegram',u.id,u.id::text,'pending',0,1,"
                "now() - interval '1 hour', now() FROM users u WHERE u.username LIKE 'z%'"
            ),
            {"inc": inc},
        )
        await db.execute(text("ANALYZE notifications"))
        await db.commit()

        batch = await claim_batch(db, worker_id="w", now=datetime.now(UTC), limit=10)
        assert len(batch) == 10  # claim caps at the limit from the global backlog
        assert all(n.status in ("pending", "failed") for n in batch)
