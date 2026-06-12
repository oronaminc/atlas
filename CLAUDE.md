# Atlas — Observability Alert Management Platform

FastAPI + React app on top of Alloy+Mimir+Loki+Tempo+Grafana. Two subsystems:
1. **Rule management**: DB (PostgreSQL) is the source of truth for alert rules → sync worker pushes to Mimir Ruler.
2. **Incident pipeline**: ingestion → correlation → incidents → notification delivery → ops dashboard + 3D graph.

## Architecture (data flow)

```
POST /api/v1/ingest/{provider}  (X-Atlas-Ingest-Key; durable insert → 202; Redis stream wake-up)
  → correlation_worker: claim_events (CAS+lease) → engine: dedup (fingerprint+Redis window)
      → group (AttributeTimeStrategy: group_key host>service>cluster + time window; LLMStrategy=stub)
      → incident attach/create (pg_advisory_xact_lock(group_key) on PG — no split-brain)
  → notification_worker: fan_out_pending (incidents.notified_at CAS → routes → member targets)
      → deliver_once: claim (CAS+lease) → quota → TokenBucket throttle → channel.send → mark
  → UI: /ops dashboard (10s poll) · /graph 3D explorer (manual refresh) · /settings admin config
```

## Invariants — do not break

- **X-Scope-OrgID: system** injected exactly once in `backend/app/integrations/base.py::make_client()`; never per-call.
- **At-least-once + idempotency**: outbox rows (`notifications`) created before side effects; `UNIQUE(incident_id, channel, recipient_user_id)`; duplicate send on crash-in-send-commit-gap is accepted, lost sends are not.
- **Replica safety = PG CAS + 60s lease** (`app/notifications/outbox.py`, `correlation_worker.claim_events`): `UPDATE ... WHERE claimed_at IS NULL OR claimed_at < now-lease`; `FOR UPDATE SKIP LOCKED` is a PG-only optimization, the CAS is the correctness guard. `mark_*`/`defer` must clear `claimed_at`.
- **Abstraction boundaries**: new alert source = module in `app/providers/` + registry entry; new channel = module in `app/notifications/channels/` + registry entry. The engine/worker never see provider/channel specifics. `llm_similar` edge kind + `LLMStrategy` are reserved stubs.
- **RBAC reuse**: `require_admin`/`require_editor`/`get_current_user` from `core/deps.py`; group-manager logic in `services/permissions.py`. Don't invent new roles.
- **Air-gap**: no CDN loads (Monaco bundled in `src/lib/monaco.ts`; drei banned — its Text fetches fonts remotely). npm deps must be pure tarballs (no install scripts). Internal mirrors via `.gitlab-ci.yml` variables.
- Every write endpoint: `services/audit.py::record_audit`; rule mutations also `mark_ruler_pending`.
- Responses: envelope `{data, error, meta}`; cursor pagination. Secrets: env only; DB-stored tokens Fernet-encrypted + masked (`********`) in responses.
- Migrations: 0001 is metadata-based and pinned to its original table list — **it also pre-creates all enum types and current columns on fresh DBs**, so later migrations need `checkfirst`/inspector guards (see 0002/0003). New migrations = explicit ops.
- `AwareDateTime` (models/base.py) for datetime columns compared in Python (SQLite drops tzinfo).
- UI strings Korean (ko default locale); code comments/docs English. New screens: `pnpm build` must stay at 0 type errors.

## 3D graph refresh switch

`/graph` is manual-refresh by design. To enable polling: set
`GRAPH_REFRESH_INTERVAL_MS` in `frontend/src/features/graph/config.ts` to a
millisecond number (it feeds TanStack Query `refetchInterval` in
`use-graph-data.ts`). Nothing else changes.

## Commands

```bash
# backend (from backend/)
uv run pytest -q                                  # 125 SQLite tests
uv run ruff check . && uv run black --check .
ATLAS_PG_TEST_URL=postgresql+asyncpg://atlas:atlas@127.0.0.1:5432/atlas uv run pytest tests/pg -q   # real-PG concurrency
./scripts/pg_concurrency_test.sh                  # same, boots compose postgres
uv run alembic upgrade head
uv run python scripts/create_admin.py admin@example.com admin <pw>
uv run python scripts/seed_demo.py                # demo incidents/notifications for /ops + /graph

# frontend (from frontend/)
pnpm build && pnpm lint                           # typecheck + lint (1 pre-existing toast warning OK)

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
  `/opt/node22/lib/node_modules/playwright/index.mjs`; r3f canvas needs `--use-angle=swiftshader`.
- jsdelivr blocked. Working branch: `claude/epic-dijkstra-mgq4oa` (push only there).
- r3f gotcha: dashed JSX props on three elements are PIERCED (`data-x-y` → `obj.data.x.y`) — never put data-attrs on `<mesh>`.

## Status (do not redo)

All 12 original spec phases + correlation engine + notification delivery/HA + ops dashboard
(`/ops`) + 3D graph (`/graph`, fiber 8 / three / d3-force-3d, lazy chunk). 125 SQLite tests,
2 real-PG concurrency tests, 9 stats/graph tests included. Browser e2e verified: rules flow,
admin settings, ops dashboard, 3D graph (screenshots in session history).
