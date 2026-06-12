# Atlas — Observability Alert Management Platform

FastAPI + React app on top of Alloy+Mimir+Loki+Tempo+Grafana. Two subsystems:
1. **Rule management**: DB (PostgreSQL) is the source of truth for alert rules → sync worker pushes to Mimir Ruler.
2. **Incident pipeline**: ingestion → correlation → incidents → notification delivery → ops dashboard + 2D swimlane graph.

## Architecture (data flow)

```
POST /api/v1/ingest/{provider}  (X-Atlas-Ingest-Key; durable insert → 202; Redis stream wake-up)
  → correlation_worker: claim_events (CAS+lease) → engine: dedup (fingerprint+Redis window)
      → group (AttributeTimeStrategy: group_key host>service>cluster + time window; LLMStrategy=stub)
      → incident attach/create (pg_advisory_xact_lock(group_key) on PG — no split-brain)
  → notification_worker: fan_out_pending (incidents.notified_at CAS → routes → member targets)
      → deliver_once: claim (CAS+lease) → quota → TokenBucket throttle → channel.send → mark
  → UI: /ops dashboard (10s poll; incident actions ack/resolve/suppress/notify = editor+)
      · /graph 2D swimlane view (manual refresh) · /settings admin config
```

## Invariants — do not break

- **X-Scope-OrgID: system** injected exactly once in `backend/app/integrations/base.py::make_client()`; never per-call.
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
uv run pytest -q                                  # 133 SQLite tests
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
  `workers/` (sync, correlation, notification)
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

All 12 original spec phases + correlation engine + notification delivery/HA + ops dashboard
(`/ops`) + 2D swimlane graph (`/graph`, hand-rolled SVG + d3-scale, lazy chunk; replaced the
former 3D view — three/r3f/d3-force-3d removed) + incident suppression (status enum value
`suppressed`, migration 0004: reversible mute, excluded from active lists/stats, still absorbs
alerts without re-notifying; editor+ via /ops detail dialog) + RBAC UI alignment (nav/route
guards admin pages; incident + receiver-test actions gated editor+). 133 SQLite tests + 6 vitest,
2 real-PG concurrency tests, 9 stats/graph tests included. Browser e2e verified: rules flow,
admin settings, ops dashboard, 2D swimlane graph, 3-role RBAC + suppression flow
(screenshots in session history).
