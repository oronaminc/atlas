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

Baselines are container-relative (4 vCPU / 16GB reference) — re-measure after
perf changes and compare trends/ratios, not absolutes.

## Partitioning (baked into the baseline)

`alert_events` is RANGE-partitioned by `received_at` from the **0001 baseline**
(daily partitions created at runtime by `maintenance_worker`); there is no
longer a separate conversion migration to re-verify. To load-test it: seed via
COPY (`seed_events --rows 10000000`), run a maintenance pass, then `query_bench`
+ time `app.api.v1.stats._alert_counts` for the trend — assert partition pruning
(EXPLAIN: only recent partitions scanned, no full seq scan). SQLite (unit tests)
stays a plain table; partition ops are PG-only.

## Notification scale

`fanout_storm` drives the real pipelined `deliver_once` over **per-group
channels** (no global routes): it seeds one group mapped to an l2 + N telegram
`GroupChannel`s, and incidents carrying that l2. Dedup is
`UNIQUE(incident_id, channel, recipient_address)`. claim @high pending: EXPLAIN
the claim — must be Index Scan using **`ix_notifications_claim` `(priority,
created_at)`** (partial `WHERE status IN ('pending','failed')` on PG), no Seq
Scan, no Sort. `TRUNCATE notifications, group_channels, group_service_codes`
between runs.

## Pitfalls (hit while building this)

- `fanout_storm` reruns accumulate groups + group_channels → reruns multiply
  targets. `TRUNCATE notifications, group_channels, group_service_codes;` between
  runs. (The script also marks pre-existing incidents `notified_at = now()` so
  only its fresh incidents fan out.)
- Quotas/rate are **env now** (`NOTIFY_QUOTA_GROUP_PER_HOUR` default 30,
  `NOTIFY_QUOTA_GLOBAL_PER_DAY` default 500, `NOTIFY_RATE_PER_SECOND` 25) — export
  high quotas before a storm or the default 30/group/h freezes sends at 30.
- asyncpg `copy_records_to_table` has no binary jsonb encoder — seeder uses
  text-format COPY.
- Run `ANALYZE alert_events` after bulk seed (seeder does) or plans lie.
- Numbers are container-relative; compare trends/ratios, not absolutes.
- Correlation worker log: `INFO correlated N` lines = batch sizes; if it logs
  exactly 100 every ~10s the stream is empty and you're seeing the 5s-block
  drain mode, not the streaming mode.
