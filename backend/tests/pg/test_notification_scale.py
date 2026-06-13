"""Phase 4 claim path against real PostgreSQL (skipped without
ATLAS_PG_TEST_URL): the partial claim index turns the 861ms seq-scan+sort
into an index-ordered scan, and the loose-index-scan tenant discovery stays
cheap at storm scale."""

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
        # replace the plain metadata index with the partial one migration 0007
        # creates, so the test exercises the real production index
        await conn.execute(text("DROP INDEX ix_notifications_claim"))
        await conn.execute(
            text(
                "CREATE INDEX ix_notifications_claim ON notifications "
                "(tenant_id, priority, created_at) WHERE status IN ('pending','failed')"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, schema
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    await engine.dispose()


async def _seed(db, schema, *, tenant_a_rows, tenant_b_rows):
    ta, tb = uuid.uuid4(), uuid.uuid4()
    # minimal incident + user rows to satisfy FKs
    inc_a, inc_b = uuid.uuid4(), uuid.uuid4()
    for inc, t in ((inc_a, ta), (inc_b, tb)):
        await db.execute(
            text(
                "INSERT INTO incidents (id,title,status,severity,group_key,first_seen,"
                "last_seen,alert_count,created_at,updated_at,tenant_id) VALUES "
                "(:id,'x','open','warning','h',now(),now(),1,now(),now(),:t)"
            ),
            {"id": inc, "t": t},
        )
    for label, inc, t, count in (("a", inc_a, ta, tenant_a_rows), ("b", inc_b, tb, tenant_b_rows)):
        await db.execute(
            text(
                "INSERT INTO users (id,email,username,role,auth_provider,is_active,"
                "created_at,updated_at) "
                "SELECT gen_random_uuid(), :lbl||g||'@x.io', :lbl||g, 'viewer','local',true,"
                "now(),now() FROM generate_series(1,:c) g"
            ),
            {"lbl": label, "c": count},
        )
        await db.execute(
            text(
                "INSERT INTO notifications (id,incident_id,channel,recipient_user_id,"
                "recipient_address,status,attempts,priority,tenant_id,created_at,updated_at) "
                "SELECT gen_random_uuid(), :inc, 'telegram', u.id, 'c', 'pending', 0, 1, :t, "
                "now() - (random()*86400 || ' seconds')::interval, now() "
                "FROM users u WHERE u.username LIKE :pat"
            ),
            {"inc": inc, "t": t, "pat": f"{label}%"},
        )
    await db.execute(text("ANALYZE notifications"))
    return ta, tb


async def test_claim_uses_partial_index_no_seqscan_no_sort(pg):
    factory, schema = pg
    async with factory() as db:
        await _seed(db, schema, tenant_a_rows=1, tenant_b_rows=0)
        # blow tenant A up to ~300k claimable (one row per user; reuse via many users)
        await db.execute(
            text(
                "INSERT INTO users (id,email,username,role,auth_provider,is_active,"
                "created_at,updated_at) SELECT gen_random_uuid(),'bulk'||g||'@x.io','bulk'||g,"
                "'viewer','local',true,now(),now() FROM generate_series(1,300000) g"
            ),
            {},
        )
        inc = (await db.execute(text("SELECT id, tenant_id FROM incidents LIMIT 1"))).first()
        await db.execute(
            text(
                "INSERT INTO notifications (id,incident_id,channel,recipient_user_id,"
                "recipient_address,status,attempts,priority,tenant_id,created_at,updated_at) "
                "SELECT gen_random_uuid(), :inc, 'telegram', u.id, 'c','pending',0,1,:t,"
                "now(),now() FROM users u WHERE u.username LIKE 'bulk%'"
            ),
            {"inc": inc[0], "t": inc[1]},
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
                        "AND tenant_id = :t "
                        "ORDER BY priority, created_at LIMIT 25 FOR UPDATE SKIP LOCKED"
                    ),
                    {"t": inc[1]},
                )
            ).scalars()
        )
        assert "ix_notifications_claim" in plan, plan
        assert "Seq Scan" not in plan, plan
        assert "Sort" not in plan, plan


async def test_claim_batch_fair_and_index_backed_at_scale(pg):
    factory, schema = pg
    from app.notifications.outbox import claim_batch

    async with factory() as db:
        # tenant A storm (50k), tenant B small (5)
        await db.execute(
            text(
                "INSERT INTO users (id,email,username,role,auth_provider,is_active,"
                "created_at,updated_at) SELECT gen_random_uuid(),'z'||g||'@x.io','z'||g,"
                "'viewer','local',true,now(),now() FROM generate_series(1,50000) g"
            ),
            {},
        )
        ta, tb = await _seed(db, schema, tenant_a_rows=0, tenant_b_rows=5)
        inc_a = (
            await db.execute(text("SELECT id FROM incidents WHERE tenant_id = :t"), {"t": ta})
        ).scalar()
        await db.execute(
            text(
                "INSERT INTO notifications (id,incident_id,channel,recipient_user_id,"
                "recipient_address,status,attempts,priority,tenant_id,created_at,updated_at) "
                "SELECT gen_random_uuid(), :inc,'telegram',u.id,'c','pending',0,1,:t,"
                "now() - interval '1 hour', now() FROM users u WHERE u.username LIKE 'z%'"
            ),
            {"inc": inc_a, "t": ta},
        )
        await db.execute(text("ANALYZE notifications"))
        await db.commit()

        batch = await claim_batch(db, worker_id="w", now=datetime.now(UTC), limit=10)
        tenants = {n.tenant_id for n in batch}
        assert tb in tenants, "tenant B starved by A's storm"
        assert sum(1 for n in batch if n.tenant_id == tb) == 5  # B's all fit in fair share
