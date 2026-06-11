# Atlas — Observability Alert Management Platform

Alert rule management web app on top of Alloy+Mimir+Loki+Tempo+Grafana (FastAPI + React).
**The DB (PostgreSQL) is the source of truth for rules** → sync worker pushes to Mimir Ruler.

## Hard rules (fixed by spec)

- Every Mimir/Alertmanager/Loki call carries `X-Scope-OrgID: system`.
  **Injected exactly once in `backend/app/integrations/base.py::make_client()`** — never set per-call.
- Stack is fixed: Python 3.12/FastAPI/SQLAlchemy 2.0 async/Alembic, React 18/Vite/Tailwind v3/shadcn, uv + pnpm.
- Responses use envelope `{data, error, meta}`; pagination is cursor-based.
- Every write goes through `services/audit.py::record_audit`. Emergency apply sets `emergency=true`.
- Secrets only via env. Receiver config secrets (url/api_key/...) are Fernet-encrypted at rest, masked in responses.
- After any frontend change: `pnpm build` must pass with 0 type errors.
- Monaco is bundled locally (`src/lib/monaco.ts`) — no CDN loading (air-gapped target).
- UI strings stay Korean (ko is the default locale; en via i18n). Code comments/docs are English.

## Structure (map)

- `backend/app/`: `api/v1/` (routers), `core/` (config/security/deps/pagination), `models/`, `schemas/`,
  `services/` (permissions/rule_sync/rule_validate/audit), `integrations/`, `workers/sync_worker.py`
- `frontend/src/`: `pages/`, `components/{ui,common,layout}`, `features/`, `api/` (client.ts/queries.ts), `hooks/`, `lib/`
- `deploy/`: `k8s/{base,overlays/{dev,prod}}` (kustomize), `flux/` (CD), `kind-up.sh`
- CI: `.gitlab-ci.yml` (internal mainline: kaniko → GitLab registry), `.github/workflows/build.yml` (GitHub)

## RBAC summary

admin=everything / editor=rule CRUD within own group/server scope + emergency apply / viewer=read-only /
group manager=group members + group-scoped rules / scope=user rules: owner+admin only / global rule writes: admin only.

## Verify commands (always after changes)

- backend: `cd backend && uv run pytest -q && uv run ruff check . && uv run black --check .`
- frontend: `cd frontend && pnpm build && pnpm lint`
- k8s manifests: `kubectl kustomize deploy/k8s/overlays/dev | kubeconform -strict -summary -`
- Detailed procedures: skills in `.claude/skills/` (backend-check, frontend-check, e2e-browser, k8s-validate)

## Deployment pipeline (user's goal)

Final target is an internal-network k8s cluster. GitLab CI (test → kaniko build → registry,
tags `main-<iid>-<sha>`) → Flux CD (`deploy/flux/`, image automation commits new tags to prod
overlay markers). Internal mirror endpoints are `.gitlab-ci.yml` variables.
Never commit atlas-secrets in plaintext (SOPS/SealedSecrets).

## Environment caveats (this cloud session)

- No Docker daemon → cannot build images or run kind. Tests run on SQLite (aiosqlite).
- Playwright: browsers at `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, library via
  `import ... from "/opt/node22/lib/node_modules/playwright/index.mjs"`.
- Some CDNs (jsdelivr) are blocked.
- Working branch: `claude/epic-dijkstra-mgq4oa` (push only to this branch).

## Correlation engine (KeepHQ-style, implemented)

3 stages in `services/correlation/`: dedup (fingerprint + Redis window) → group
(`AttributeTimeStrategy`: priority-first group_key host>service>cluster + time window;
`LLMStrategy` = stub) → incident (attach/create, timeline, severity=max).
- Ingest: `POST /api/v1/ingest/{provider}` (X-Atlas-Ingest-Key static auth, 202 after durable
  insert; correlation async). Providers in `app/providers/` (alertmanager = #1; new source =
  new module + registry entry, engine untouched).
- Worker `workers/correlation_worker.py`: PG-poll for incident_id IS NULL (source of truth)
  + Redis stream `atlas:alerts:in` wake-up. Dedup = increment prior row's dedup_count, drop dup row.
- Config DB-backed (`correlation_config` single row, seeded 300s/900s/host,service,cluster),
  admin-edited at `/settings` (UI) or PATCH `/api/v1/correlation-config`, audited.
- Incidents: list/detail/ack/resolve (editor+, audited, resolved = terminal → 409).
- Migration 0001 is pinned to its original table list (metadata grows); 0002+ = explicit ops.

## Notification delivery + HA (implemented)

- Outbox pattern: `notifications` table = persisted intent; UNIQUE(incident, channel,
  recipient) idempotency; at-least-once. Claim = CAS + 60s lease (`app/notifications/outbox.py`);
  PG adds FOR UPDATE SKIP LOCKED; crashed pod's claims expire → another pod resumes.
- Correlation worker now claims via same CAS+lease (`claim_events`); engine takes
  `pg_advisory_xact_lock(group_key)` on PG to serialize find-or-create (no split-brain).
- Channels in `app/notifications/channels/` (Telegram #1 httpx, Email #2 SMTP-env,
  registry; token Fernet in `notification_settings`). New channel = module + registry entry.
- `workers/notification_worker.py` (separate pod, prod replicas=2): fan-out
  (incidents.notified_at CAS → route match min_severity → group member targets) then
  deliver (quota check → TokenBucket throttle → send → mark). Quota breach = defer to
  window reset. Backoff 30s×2^n cap 1h, dead at 5 attempts.
- API: /notification-settings + /notification-routes + /notification-recipients (admin),
  POST /incidents/{id}/notify (editor+), /notifications list. users PATCH accepts
  telegram_chat_id. UI on /settings page.
- Real-PG concurrency tests in `tests/pg/` (skip unless ATLAS_PG_TEST_URL; apt postgresql
  works in this env — `service postgresql start`, user/db atlas/atlas).
- `AwareDateTime` in models/base.py: use for new datetime columns compared in Python
  (SQLite drops tzinfo).

## Already done (do not redo)

All 12 spec phases implemented: models/migration, auth (local+OIDC)+RBAC, integrations,
full REST API, sync worker, 11 frontend screens, k8s + GitLab CI + Flux. 81 backend tests.
Headless-browser E2E verified the main flows. Correlation engine (37 tests) +
notification delivery/HA (35 tests + 2 real-PG concurrency tests). 116 SQLite tests total.
