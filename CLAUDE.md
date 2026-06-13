# Atlas — Observability Alert Management Platform

FastAPI + React app on top of Alloy+Mimir+Loki+Tempo+Grafana. Two subsystems:
1. **Rule management**: DB (PostgreSQL) is the source of truth for alert rules → sync worker pushes to Mimir Ruler.
2. **Incident pipeline**: ingestion → correlation → incidents → notification delivery → ops dashboard + 2D swimlane graph.

## Architecture (data flow)

```
Alloy (per subsidiary, sets X-Scope-OrgID) → Mimir org → AM webhook → POST /api/v1/ingest/{provider}/{org}
  (mimir_org_map: org → tenant_id, stamped on alert_events; un-orged legacy route = default tenant/key)
  → correlation_worker: claim_events (CAS+lease) → engine: dedup (fingerprint+Redis window)
      → group (AttributeTimeStrategy: group_key host>service>cluster + time window; LLMStrategy=stub)
      → incident attach/create (pg_advisory_xact_lock(group_key) on PG — no split-brain)
  → notification_worker: fan_out_pending (incidents.notified_at CAS → routes → member targets)
      → deliver_once: claim (CAS+lease) → quota → TokenBucket throttle → channel.send → mark
  → UI: /ops dashboard (10s poll; incident actions ack/resolve/suppress/notify = editor+)
      · /graph 2D swimlane view (manual refresh) · /settings admin config
```

## Invariants — do not break

- **X-Scope-OrgID** injected exactly once in `backend/app/integrations/base.py::make_client(base_url, org)`;
  never per-call. `org` resolves from the tenant (`mimir_org_map`); default = `MIMIR_TENANT_ID` ("system").
- **Tenancy choke point** (`core/tenancy.py`): `get_current_user` sets `session.info["tenant_scope"]`;
  a global `do_orm_execute` listener auto-filters every SELECT on `TenantScoped` models and
  `before_flush` stamps new rows. Endpoints NEVER write tenant filters by hand. `tenant_id` is
  nullable: NULL = legacy/system rows, visible only to HQ (users.tenant_id NULL). Workers run
  unscoped and stamp per-row from the event/incident. Correlation dedup/window/advisory-lock and
  fanout route-match are keyed by tenant — same host on two tenants must NEVER merge (tested).
- **At-least-once + idempotency**: outbox rows (`notifications`) created before side effects; `UNIQUE(incident_id, channel, recipient_user_id)`; duplicate send on crash-in-send-commit-gap is accepted, lost sends are not.
- **Replica safety = PG CAS + 60s lease** (`app/notifications/outbox.py`, `correlation_worker.claim_events`): `UPDATE ... WHERE claimed_at IS NULL OR claimed_at < now-lease`; `FOR UPDATE SKIP LOCKED` is a PG-only optimization, the CAS is the correctness guard. `mark_*`/`defer` must clear `claimed_at`.
- **Abstraction boundaries**: new alert source = module in `app/providers/` + registry entry; new channel = module in `app/notifications/channels/` + registry entry. The engine/worker never see provider/channel specifics. `llm_similar` edge kind + `LLMStrategy` are reserved stubs.
- **RBAC reuse**: `require_admin`/`require_editor`/`get_current_user` from `core/deps.py`; group-manager logic in `services/permissions.py`. Don't invent new roles.
- **Air-gap**: no CDN loads (Monaco bundled in `src/lib/monaco.ts`; no remote-font libs — the /graph SVG uses system fonts only). npm deps must be pure tarballs (no install scripts). Internal mirrors via `.gitlab-ci.yml` variables.
- Every write endpoint: `services/audit.py::record_audit`; rule mutations also `mark_ruler_pending`.
- Responses: envelope `{data, error, meta}`; cursor pagination. Secrets: env only; DB-stored tokens Fernet-encrypted + masked (`********`) in responses.
- Migrations: 0001 is metadata-based and pinned to its original table list — **it also pre-creates all enum types and current columns on fresh DBs**, so later migrations need `checkfirst`/inspector guards (see 0002/0003). New migrations = explicit ops.
- `AwareDateTime` (models/base.py) for datetime columns compared in Python (SQLite drops tzinfo).
- UI strings Korean (ko default locale); code comments/docs English. New screens: `pnpm build` must stay at 0 type errors.

## 2D graph refresh switch

`/graph` (incident swimlanes: X = time, one lane per host) is manual-refresh
by design. To enable polling: set `GRAPH_REFRESH_INTERVAL_MS` in
`frontend/src/features/graph/config.ts` to a millisecond number (it feeds
TanStack Query `refetchInterval` in `use-graph-data.ts`). Nothing else changes.
Lane cap before the "+N hosts" expander: `GRAPH_MAX_VISIBLE_LANES` (same file).

## Commands

```bash
# backend (from backend/)
uv run pytest -q                                  # 203 SQLite tests
uv run ruff check . && uv run black --check .
ATLAS_PG_TEST_URL=postgresql+asyncpg://atlas:atlas@127.0.0.1:5432/atlas uv run pytest tests/pg -q   # real-PG concurrency
./scripts/pg_concurrency_test.sh                  # same, boots compose postgres
uv run alembic upgrade head
uv run python scripts/create_admin.py admin@example.com admin <pw>
uv run python scripts/seed_demo.py                # demo incidents/notifications for /ops + /graph

# frontend (from frontend/)
pnpm build && pnpm lint                           # typecheck + lint (1 pre-existing toast warning OK)
pnpm test                                         # vitest (graph swimlane layout)

# full stack
docker compose up --build                         # pg, redis, backend, sync/correlation/notification workers, frontend

# k8s manifests
kubectl kustomize deploy/k8s/overlays/dev | kubeconform -strict -summary -
```

## Structure map

- `backend/app/`: `api/v1/` (routers incl. ingest/incidents/correlation_config/notification_admin/stats/graph),
  `core/`, `models/`, `schemas/`, `services/` (permissions/rule_sync/rule_validate/audit/correlation/),
  `providers/`, `notifications/` (channels/, fanout, outbox, delivery, throttle, settings),
  `workers/` (sync, correlation, notification, maintenance, llm)
- `frontend/src/`: `pages/` (incl. ops.tsx, graph.tsx lazy), `features/` (rules/, notifications/, ops/, graph/),
  `components/{ui,common,layout}`, `api/` (client.ts/queries.ts), `locales/{ko,en}.json`
- `deploy/`: `k8s/{base,overlays/{dev,prod}}`, `flux/`, `kind-up.sh`
- CI: `.gitlab-ci.yml` (internal: kaniko → GitLab registry + test-pg-concurrency job), `.github/workflows/build.yml`

## Deployment (user's goal)

Internal k8s. GitLab CI (test → kaniko, tags `main-<iid>-<sha>`) → Flux CD (`deploy/flux/`,
image automation commits to prod overlay markers). Secrets never plaintext in git (SOPS/SealedSecrets).

## Environment caveats (cloud session)

- No Docker daemon. Real PG available: `service postgresql start` (apt-installed; user/db atlas/atlas).
- Playwright: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, import from
  `/opt/node22/lib/node_modules/playwright/index.mjs`.
- jsdelivr blocked. Working branch: `claude/epic-dijkstra-mgq4oa` (push only there).

## Features: LLM analysis + search (2026-06-13)

**LLM incident analysis (Feature A)** — OpenAI-compatible (vLLM/Ollama/gateway
primary; external OpenAI opt-in). `llm_config` per-service (mirrors
notification_settings: tenant_id NULL=default; api_key Fernet+MASKED;
base_url empty + enabled=False by default → nothing sent until configured).
`incident_analysis` is the job-as-row (UNIQUE(incident_id), CAS+lease claim);
separate `llm_worker` pod runs it so a slow/failing LLM never blocks the
incident pipeline. `app/integrations/llm.py` = own httpx client (NOT
BaseIntegrationClient — no X-Scope-OrgID), retry+timeout, mock transport in
tests. TENANCY: the job carries the incident's stamped tenant_id; config is
resolved by THAT id → a service's incident only ever POSTs to its own
endpoint (tested A→A, never B). Redaction before prompt: secret-keyed/
secret-shaped values masked always; external endpoints additionally drop
unknown label keys + cap free-text. prompt_hash cache (re-run only on change
or ?force=true); per-service daily_quota (default 200, audited). On-demand
`POST /incidents/{id}/analyze` (editor+) + `GET .../analysis`; `auto_analyze`
flag (default off) enqueues via the worker (bounded, off the hot path).
Metrics: atlas_llm_* . /ops dialog Analyze button + polled result.

**Search (Feature B)** — `GET /search?q=&type=host|label|text&since=&limit=`,
auto-scoped by the tenancy choke point (service users see only their rows, HQ
all). host→incidents.group_key prefix (small table→/graph); label→
alert_events.labels @> {k:v} TIME-BOUNDED (default 7d, max 30d → partition
pruning) + GIN index `ix_alert_events_labels_gin` (jsonb_path_ops, migration
0009, partition-local); text→incidents.title ILIKE (no pg_trgm — air-gap).
EXPLAIN-asserted: GIN bitmap scan, no full-table seq scan, old partitions
pruned. UI: debounced global top-bar search → results dropdown → host routes
/graph, incident routes /ops?incident=<id> (ops opens the dialog from the
query param).

## Phase 5: observability (2026-06-13, final)

Terminology: a **tenant = a service** (one service has many vendors attached);
the row-level tenancy STRUCTURE from Phases 2-4 is unchanged — only labels read
"service". `tenant_id` columns/APIs keep their names.

The monitoring system must not fail silently — Prometheus metrics + k8s health
+ self-alerts, all air-gap (zero new deps; hand-rolled exposition).
- **Zero-dep registry** `app/core/metrics.py` (Counter/Gauge/Histogram + text
  0.0.4 `render()`); instruments declared in `app/core/instruments.py`. One
  registry PER PROCESS.
- **API `GET /metrics`** (`api/v1/metrics.py`, mounted at root, unauthenticated,
  infra-internal): own ingest counters + cross-pod DB-derived gauges computed at
  scrape from an UNSCOPED session (bypasses the tenancy choke point — correct for
  ops), cached `METRICS_DB_CACHE_SECONDS=15`. Never routed through public Ingress
  (NetworkPolicy + no Ingress path).
- **Each worker** runs a stdlib-asyncio server (`workers/metrics_server.py`) on
  `METRICS_PORT=9100`: `/metrics` (own counters + heartbeat) + `/healthz`
  (loop heartbeat fresh within N×interval -> liveness) + `/readyz` (PG reachable;
  Redis best-effort, surfaced via `atlas_redis_up`, never gates readiness).
- **Cardinality bound**: hot-path counters carry only fixed low-card labels
  (provider/channel/reason/outcome). Per-service series exist ONLY on soft-cap
  breach (`atlas_tenant_pending_softcap_breached{service=slug}`) — normal state =
  zero per-service series.
- **Per-service pending soft-cap**: `notification_settings.pending_softcap`
  (migration 0008, default 50000, admin-adjustable via the notification-settings
  card, audited). Alert, never shed.
- **Self-alerts**: `deploy/k8s/base/prometheus-rules.yaml` (10 rules: correlation
  backlog/stall, notif queue/oldest, soft-cap breach, default-partition>0, rollup
  stale, delivery-failure-rate, worker down, worker-loop stalled). Kept out of the
  kustomization (CRD) so kubeconform -strict stays green; apply separately.
- Scrape via pod annotations (`prometheus.io/scrape|port|path`), no Operator CRD
  needed. Overhead: +4.56µs/ingest request (~0.1%), 235 rps/worker (≥225 baseline).
- 10 observability tests (registry format, value correctness, breach-only
  cardinality, worker health/readiness, heartbeat-stale liveness).

## Phase 4: notification scale (2026-06-13)

The Phase 1 first-bottleneck, fixed against re-measured numbers:
- claim @1.3M pending: 861ms seq-scan+sort -> 0.49ms index scan. Migration 0007
  makes ix_notifications_claim a PARTIAL index (tenant_id, priority, created_at)
  WHERE status IN ('pending','failed') (PG). The Phase 2/3
  (tenant_id,status,created_at) index was NOT partial -> planner ignored it.
- send rate: 10.9/s -> 21.3/s (25/s/bot budget, ~85%). deliver_once was fully
  serial (one await channel.send at a time); now per-tenant bounded-gather
  (SEND_CONCURRENCY_CAP=16, ceil(rate*RTT)+4) pipelines the network RTT while DB
  writes stay serial (one AsyncSession isn't concurrency-safe). TokenBucket got
  an asyncio.Lock for concurrent acquire.
- quota pre-reserved at dispatch (counters incremented synchronously before the
  gather, rolled back on send failure) so concurrent sends can't slip past the
  same quota; quota defer writes the reason to last_error ("quota: group N/h
  reached") -> visible in the /ops delivery panel.
- priority: notifications.priority smallint (critical=0/warning=1/info=2) set at
  fan-out; claim orders (priority, created_at) so critical drains first.
- cross-tenant fairness: claim is round-robin — _active_tenants (PG loose index
  scan, ~3ms at 1.3M; inlined predicate, NOT a materialized CTE) finds tenants
  with claimable work, each gets an equal share, leftover refills. One
  subsidiary's storm can't starve another (tested A=50k vs B=5).
- drop unconditional sleep(5): worker loops immediately while a fan-out or
  delivery batch was full (DeliveryResult.was_full); sleeps only when idle.
- per-incident dedup unchanged (UNIQUE(incident,channel,recipient) + notified_at
  CAS already guarantee one row per recipient regardless of attached-alert
  count — now explicitly tested). at-least-once/idempotency + crash-mid-delivery
  proofs re-run green.
- backpressure: durable outbox is the bounded queue, no shedding. Phase 5 TODO:
  per-tenant pending soft-cap ALARM (alert, don't shed) + expose queue depth +
  oldest-pending age.

## Phase 3: partitioning + retention (2026-06-13)

- **alert_events = PG RANGE-partitioned by received_at, DAILY** (`alert_events_pYYYYMMDD`),
  PK(id, received_at), parent indexes materialize partition-local. SQLite (tests) stays a
  regular table — partition ops are dialect-guarded (`services/maintenance.py::_is_pg`).
- **Migration 0006** converts populated tables via CHECK-validate → rename+ATTACH:
  measured on harness-seeded **10M rows: lock window 9.6s, zero data loss, per-tenant
  counts byte-identical**. Fallback for ≥100M: full-copy + dual-write (not implemented).
- **DEFAULT partition = insert safety net**: a missing date partition NEVER fails an insert;
  `maintenance_worker` re-homes stray rows and `default_partition_count` (should be 0) is a
  Phase 5 metric. Partition creation/drops/rollups/retention-deletes all live in
  `services/maintenance.py`, driven by `workers/maintenance_worker.py` (full pass on start +
  6h, rollups every 15min, Redis lock; separate pod in compose/k8s).
- **Retention** (`retention_config`, single row, HQ-admin card in /settings, audited):
  alert_events 90d (partition DETACH+DROP, optional gzip-CSV archive to ARCHIVE_DIR —
  asyncpg COPY needs an ASYNC output callback on a DEDICATED connection),
  incidents 180d (resolved/suppressed only, cascade), notifications 90d (sent/dead),
  audit 365d. 0 = keep forever.
- **stats/trend rewrite**: `alert_stats_hourly` rollups (idempotent DELETE+INSERT, NULL-tenant
  safe, TenantScoped) + live scan only of hours after the last rolled bucket.
  **Measured @10M rows: 909ms p50 (old full-24h fetch) → 2.3ms p50 (395×)**; point queries
  flat at 0.2ms post-partition. Pruning is EXPLAIN-asserted in `tests/pg/test_partitioning.py`.
- **Engine pruning bounds**: dedup lookup bounded by dedup window; claim scan bounded by
  `CLAIM_LOOKBACK_DAYS` (default 7) — without these every partition's index gets probed.
- Gotcha: asyncpg returns `relkind` as bytes — compare `relkind::text` in migrations.

## Load-test findings (Phase 1, 2026-06-12 — drives Phases 2-5)

Harness: `backend/loadtest/` + load-test skill (zero new deps; raw-socket asyncio client).
Box: 4 vCPU / 16GB container, PG 16 + Redis local — treat as relative numbers.

- **Ingest ceiling**: ~225 rps/uvicorn-worker (p95 20ms), ~480 rps @ 4 workers.
  Overload degrades throughput (226→131 rps as concurrency rises) — no shedding/backpressure.
  `_enqueue` opens a NEW Redis conn per request ≈ 10% tax (253 vs 226 rps without).
  Insert path flat at 10M rows. 10k-alert storm: 0 errors, all 202 (durable-insert design holds).
- **Correlation worker**: keeps up at 200/s ingest (lag ≤ ~2s) — but only on the warm
  dedup-collapse path. Full path (new fingerprint: advisory lock + window scan + commit)
  ≈ 50ms/event ⇒ ~20-25 events/s/worker. WORST BUG: once the Redis stream is empty,
  the loop blocks 5s per ≤100-event batch → PG backlog drains at ≤20/s (measured 10/s);
  a 48k cold backlog took >40min. Worker restart during a storm = the storm.
- **DB growth (alert_events 1M/5M/10M, 464MB/2.3GB/4.6GB)**: indexed point queries flat
  at 0.2ms (fingerprint, claim-scan, strategy-window all fine). Degrade: `stats/trend`
  fetches the whole 24h slice into Python — 810ms p50 @ 357k rows/24h, and /ops polls it
  every 10s per viewer; `alerts_24h` count 160ms. These two, not the correlation queries,
  are the row-count casualties.
- **Notification fan-out**: routes are GLOBAL — every enabled route matches every
  un-notified incident (no group/host scoping): 5k leftover incidents × 300-member route
  = 1.5M outbox rows in minutes. `claim_batch` at 1.3M pending = seq scan + 51MB disk
  sort = **754ms per 50-row claim**. Send pipeline is serial: ~92ms/send (2 quota COUNTs
  + 50ms RTT + mark) ⇒ **10.8 sends/s** even with throttle at 25/s and no sleep; prod
  worker's unconditional sleep(5) caps it at ~5/s ⇒ 3,000-recipient storm ≈ 10min.
  Default quota (30/group/h) silently freezes storms at 30 sends, rest defer.

**Priority for later phases (measured, not guessed):**
1. (Phase 4) Notification path: per-incident batching/dedup before outbox, route scoping,
   index for claim (status,created_at partial), pipelined sends, drop sleep(5) when busy.
2. (Phase 3/perf) Correlation drain mode: loop immediately while a full batch was claimed;
   full-path cost 50ms/event needs batching of commits/locks. Trend/24h-count queries →
   pre-aggregation or partition pruning (alert_events partitioning).
3. (Phase 5) The 30/group/h quota freeze and stream-empty drain mode are silent — metrics
   for queue depth/lag/defer-rate are not optional.
4. (Phase 2) Tenancy adds a tenant key to every hot query above — do it before partitioning.

## Status (do not redo)

Phase 3 retention/partitioning: daily PG partitions + retention policies + hourly stats
rollups (see Phase 3 section above; 7 maintenance tests + 3 real-PG partition tests).
Phase 2 multi-tenancy: hierarchical row-level tenancy (HQ = tenant_id NULL sees all; tenant users
locked to their tenant), Mimir-org-driven attribution (`tenants` + `mimir_org_map` + org-qualified
ingest webhooks provisioned by `services/am_provision.py` behind AM_PROVISION_ENABLED), per-tenant
notification settings/bot token/quotas/throttle + tenant-scoped routes (kills the Phase 1 global-route
explosion), per-org rule sync + HQ alerts-proxy fan-out, tenants admin UI (/settings, HQ) + user
reassignment (/users, HQ) + /ops tenant filter+column, migration 0005 (batched backfill to default
"system" tenant; create_admin bootstraps HQ). 22 tenancy tests (isolation/pipeline/RBAC matrix).
All 12 original spec phases + correlation engine + notification delivery/HA + ops dashboard
(`/ops`) + 2D swimlane graph (`/graph`, hand-rolled SVG + d3-scale, lazy chunk; replaced the
former 3D view — three/r3f/d3-force-3d removed) + incident suppression (status enum value
`suppressed`, migration 0004: reversible mute, excluded from active lists/stats, still absorbs
alerts without re-notifying; editor+ via /ops detail dialog) + RBAC UI alignment (nav/route
guards admin pages; incident + receiver-test actions gated editor+). 180 SQLite tests + 6 vitest,
2 real-PG concurrency tests, 9 stats/graph tests included. Browser e2e verified: rules flow,
admin settings, ops dashboard, 2D swimlane graph, 3-role RBAC + suppression flow, multi-tenant
HQ/subsidiary isolation (screenshots in session history).
