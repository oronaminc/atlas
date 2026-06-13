---
name: load-test
description: Repeatable load/scale harness (ingest ceiling, correlation lag, alert storm, DB growth, notification fan-out). Use before/after any performance work or capacity question.
---

# Load testing Atlas

Harness: `backend/loadtest/` — custom asyncio, **zero new deps** (stdlib +
asyncpg/httpx already in the venv; raw-socket HTTP client so the generator
is never the bottleneck). Air-gap safe, runs fully local. Locust/k6 rejected:
new pip deps resp. binary download.

## Setup (PG + Redis + backend + workers)

```bash
service postgresql start && redis-server --daemonize yes
PGPASSWORD=atlas psql -h 127.0.0.1 -U atlas -d atlas -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
cd backend
export DATABASE_URL="postgresql+asyncpg://atlas:atlas@127.0.0.1:5432/atlas" \
  SECRET_KEY="load-test-secret-key-with-enough-length-12345" \
  FERNET_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  INGEST_API_KEY="load-test-key" REDIS_URL="redis://127.0.0.1:6379/0"
uv run alembic upgrade head
nohup uv run uvicorn app.main:app --port 8000 --workers 4 &      # 1 worker for per-core numbers
nohup uv run python -m app.workers.correlation_worker &           # for lag/storm scenarios
nohup uv run python -m loadtest.telegram_stub --latency-ms 50 &   # for fanout scenario
```

## Scenarios (run from backend/, env as above)

```bash
uv run python -m loadtest.ingest_load --stages 2,4,8,16,32,64 --duration 20   # ceiling + latency ramp
uv run python -m loadtest.correlation_lag --rate 100 --duration 30            # keep-up + drain rate
uv run python -m loadtest.storm --alerts 10000 --concurrency 32               # burst + recovery watch
uv run python -m loadtest.seed_events --rows 10000000                         # bulk history via COPY
uv run python -m loadtest.query_bench                                          # hot-query p50/p95/p99
uv run python -m loadtest.fanout_storm --recipients 300 --incidents 10        # outbox depth + send rate
```

Baseline numbers (2026-06-12, 4 vCPU / 16GB container): see CLAUDE.md
"Load-test findings". Re-run after perf changes and diff against those.

## Partition-migration proof (Phase 3 procedure)

To re-verify migration 0006 on a populated table: reset PG to revision 0005
(`uv run alembic downgrade`/fresh schema + `upgrade 0005`), seed
(`uv run python -m loadtest.seed_events --rows 10000000` — stamps two
synthetic tenant ids), snapshot `count(*)` + per-tenant counts, then time
`uv run alembic upgrade head` (prints `0006: conversion lock window = Ns`)
and re-compare counts. 2026-06-13 result @10M: 9.6s lock window, zero loss.
After conversion, `query_bench` still works against the partitioned parent;
run a maintenance pass + `app.api.v1.stats._alert_counts` timing for the
trend before/after (909ms -> 2.3ms p50 @10M).

## Pitfalls (hit while building this)

- `fanout_storm` reruns accumulate groups+routes: **routes are global**, every
  enabled route matches every un-notified incident → reruns multiply targets.
  `TRUNCATE notifications; DELETE FROM notification_routes;` between runs.
- `notification_settings` row doesn't exist until first read — UPDATEing
  quotas on a fresh DB no-ops and the default 30/group/h freezes sends at 30.
- asyncpg `copy_records_to_table` has no binary jsonb encoder — seeder uses
  text-format COPY.
- Run `ANALYZE alert_events` after bulk seed (seeder does) or plans lie.
- Numbers are container-relative; compare trends/ratios, not absolutes.
- Correlation worker log: `INFO correlated N` lines = batch sizes; if it logs
  exactly 100 every ~10s the stream is empty and you're seeing the 5s-block
  drain mode, not the streaming mode.
