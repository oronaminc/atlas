# Atlas — Observability Alert Management Platform

FastAPI (async SQLAlchemy) + React/Vite/TS on top of Alloy + Mimir + Loki + Tempo + Grafana.
atlas is a **SAML/OIDC-gated SP** and a Mimir **read-only consumer**. Two subsystems:

1. **Rule & threshold management (no PromQL)** — alert rules are *pulled read-only*
   from the Mimir Ruler into an atlas cache; the operator never writes PromQL. A
   "threshold" = pick a pulled rule and override a single number.
2. **Incident pipeline** — ingest → correlation → incidents → per-group
   notification delivery → ops dashboard + incident swimlane graph.

## Architecture (data flow)

```
Alertmanager webhook ──▶ POST /api/v1/ingest/{provider}   (static-key auth; durable insert → 202)
  split alerts[]: firing → store + enqueue ; resolved → auto-resolve by fingerprint (system actor)
  └▶ correlation_worker: claim (CAS+lease) → dedup (fingerprint+Redis window)
        → threshold filter (alert value vs override; fail-open) → group by cmdb_service_l2_code
        → incident attach/create (pg_advisory_xact_lock(group_key))
  └▶ notification_worker: fan_out (incidents.notified_at CAS → l2 → groups → GroupChannels)
        → deliver_once: claim → quota → per-channel TokenBucket → channel.send → mark
  └▶ UI: /ops (10s poll) · /graph (incident swimlanes) · /settings (admin) · /alerts /incidents
```

Mimir read side (no PromQL authored anywhere):
```
mimir_sync_worker (own pod) ──▶ Prometheus rules API + AM silences ──▶ mimir_rules / mimir_silences cache
GET /rules/pulled, /silences, /labels[/{name}/values]  serve the cache / proxy the label API
```

## Invariants — do not break

- **No PromQL, ever.** atlas never authors/accepts/exposes a PromQL or `expr`
  input. Rules are read-only from the cache; thresholds override a number;
  dropdown/autocomplete values come from the Mimir label API.
- **Visibility = l2, not tenancy** (`core/visibility.py`). `get_current_user`
  calls `set_l2_scope` once/request; a global `do_orm_execute` listener adds
  `cmdb_service_l2_code IN (scope)` to every SELECT on visibility-scoped models.
  Scope = the user's groups' `group_service_codes`. **Admins bypass.** NULL-l2
  rows are invisible to non-admins. Endpoints never write l2 filters by hand.
  (There is **no `tenant_id`** column anymore; `MIMIR_TENANT_ID` is only the
  single Mimir X-Scope-OrgID.)
- **X-Scope-OrgID** injected once in `integrations/base.py::make_client`, never
  per-call; default `MIMIR_TENANT_ID="system"`.
- **At-least-once + idempotency**: outbox rows (`notifications`) created before
  side effects; dedup `UNIQUE(incident_id, channel, recipient_address)`; a
  duplicate send across a crash gap is accepted, a lost send is not.
- **Replica safety = PG CAS + lease** (`workers/*` claim loops, `incident_analysis`,
  notification outbox): `UPDATE … WHERE claimed_at IS NULL OR claimed_at < now-lease`.
  `FOR UPDATE SKIP LOCKED` is a PG-only optimization; the CAS is the guard.
  `mark_*`/`defer` must clear `claimed_at`.
- **Per-group channels, nothing global**: each user group owns its Telegram bot
  token + chat-id(s), email(s), and on-call webhook (`GroupChannel`). Fanout
  routes incident `cmdb_service_l2_code` → groups mapped to it → their channels.
- **Incident lifecycle**: statuses open/acknowledged/resolved/suppressed;
  `resolved` is terminal. Detaching the **last** alert → 409 (delete the incident
  to dissolve). Delete frees alerts (`incident_id=NULL`, still browsable), drops
  timeline + pending/failed notifications, keeps sent/dead. Auto-resolve (system
  actor) when **all** an incident's alerts are resolved — on both the AM-resolve
  and detach paths.
- **Abstraction boundaries**: new alert source = module in `app/providers/` +
  registry entry; new channel = module in `app/notifications/channels/` +
  registry entry. Engine/worker never see provider/channel specifics.
- **RBAC**: `require_admin`/`require_editor`/`get_current_user` from
  `core/deps.py`; group-manager logic in `services/permissions.py`. Roles are
  `admin|editor|viewer` only — don't invent roles.
- **Single-row admin config pattern** (reuse it, don't invent a parallel one):
  one row + `get_or_create` helper seeding defaults + admin `GET`/`PATCH`
  (`require_admin`, audited) + a `/settings` card. Instances: `retention_config`,
  `notification_defaults`, `llm_config`, `mimir_query_config`, `saml_config`.
- **Secrets**: env only for infra creds; DB-stored secrets (bot tokens, SP private
  key, LLM api_key) Fernet-encrypted (`core/security.py`) + MASKED (`********`)
  in responses, and only overwritten on PATCH when a non-masked value is sent.
- **Responses**: envelope `{data, error, meta}`. Pagination: cursor by default;
  numbered (`?page=&page_size=`) via `core/pagination.offset_page` for users/audit.
- **Every write endpoint** calls `services/audit.py::record_audit`.
- **Migrations**: `0001_imp_baseline` is metadata-based and **pinned** — it
  pre-creates current tables/enums/columns on a fresh DB, so every later delta
  must be idempotent (metadata `create_all(tables=[…])` for new tables;
  inspector-guarded `batch_alter_table` for column adds; PG enum values via
  `ADD VALUE IF NOT EXISTS`). Alembic revision id ≤ 32 chars.
- `AwareDateTime` (models/base.py) for datetimes compared in Python (SQLite drops tzinfo).
- **Air-gap**: no CDN/remote-font loads (/graph SVG uses system fonts); npm deps
  pure tarballs. (Python SAML libs `python3-saml`/`xmlsec` are an accepted
  exception — installed normally.)
- UI strings Korean (`ko` default locale); code comments/docs English.
  `pnpm build` must stay at 0 type errors.

## Auth

- **Local** password → JWT access token + httpOnly **refresh cookie**
  (`atlas_refresh`, path `{ROOT_PATH}/api/v1/auth`). `core/security.create_token`.
- **OIDC** (auth-code) and **SAML 2.0** SSO. SAML is admin-configured in
  `saml_config` (SP key/cert + IdP metadata XML + attribute mapping
  givenName/distinguishedName/mail); `python3-saml` validates the assertion at
  `POST /auth/saml/acs`; `GET /auth/saml/login` builds the AuthnRequest;
  `GET /auth/saml/metadata` serves SP metadata. SP entityID/ACS derive from
  `ATLAS_PUBLIC_URL` (carries `/alert-hub`).
- **JIT** (OIDC + SAML): first login creates a `viewer`; later logins match
  (SAML key = `saml_uid` = the DN) and refresh display name only — an
  admin-changed role is never overwritten. SAML `username` = a stable handle from
  the DN's CN (fallback `saml-<sha1[:8]>` for non-ASCII CNs); email = `mail` or a
  synthesized `…@saml.invalid`. `memberOf`/groups not consumed yet.

## Mimir read-cache + label proxy

- `mimir_sync_worker` (own pod, advisory-locked) refreshes `mimir_rules` (config
  + eval state) and `mimir_silences` from Mimir every `MIMIR_SYNC_INTERVAL_SECONDS`.
- Threshold filter (`services/threshold.py`): an ingested alert's `value` vs the
  effective threshold (per-server `cmdb_ci` override > per-service label override >
  the rule's `atlas_threshold`/`atlas_compare` from cache); missing → **fail open**.
- Label autocomplete (`/labels`) is bounded by `mimir_query_config.label_query_lookback_hours`
  (default 1h, admin-tunable) — Mimir 422s an unbounded label query against a stale
  bucket index. Upstream Mimir errors are surfaced with their real status (not a blanket 502).
- Silences: read from cache (all users); write goes straight to Alertmanager
  (editor+), atlas builds the matcher from service (`cmdb_service_l2_code`) or
  server (`cmdb_ci`).

## Other features

- **LLM incident analysis**: `llm_config` (OpenAI-compatible; enabled=False until
  set; api_key Fernet+MASKED). `incident_analysis` job-as-row (CAS+lease) run by a
  separate `llm_worker`. On-demand `POST /incidents/{id}/analyze` (editor+) +
  `GET .../analysis`; `auto_analyze` flag off the hot path.
- **Search**: `GET /search?q=&type=host|label|text` — l2-scoped; label search is
  time-bounded + GIN-indexed.
- **Partitioning/retention**: `alert_events` daily PG range partitions;
  `retention_config` policies; hourly `alert_stats_hourly` rollups; driven by
  `maintenance_worker`. SQLite (tests) stays a plain table (dialect-guarded).
- **Observability**: zero-dep metrics registry (`core/metrics.py`), `GET /metrics`,
  per-worker `/healthz`+`/readyz`, `deploy/k8s/base/prometheus-rules.yaml`.

## Subpath deploy (`/alert-hub`, shares a host with Grafana)

Same prefix dev+prod; only the host differs (`atlas-dev.` / `atlas.sktelecom.com`).
Prefix is not hardcoded:
- Frontend (build-time): `VITE_BASE_PATH=/alert-hub/` → Vite `base`, router
  `basename`, API base, dev proxy, monaco chunk URLs. Empty `/` = local dev/test.
- Backend (runtime): `ROOT_PATH=/alert-hub` → FastAPI `root_path` (docs under
  `/api`) + the auth **cookie path** (browser-facing → MUST carry the prefix or
  refresh drops the session). Routes stay at `/api/v1`. `ATLAS_PUBLIC_URL`/
  `FRONTEND_URL` carry the prefix; `CORS_ORIGINS` is origin-only.
- Ingress: single rule `path: /alert-hub(/|$)(.*)` → `atlas-frontend:80`,
  `rewrite-target: /$2` (strips the prefix; app serves at root internally).

## Commands

```bash
# backend (from backend/)
uv run pytest -q                                   # ~280 SQLite tests
uv run ruff check . && uv run black --check .
uv run alembic upgrade head                        # 0001 → 0009
uv run python scripts/create_admin.py admin@example.com admin <pw>

# frontend (from frontend/)
pnpm build && pnpm lint                            # 0 type errors (1 pre-existing use-toast warning OK)
pnpm test                                          # vitest (graph swimlane layout)

# k8s manifests (CI renders base + overlays/dev)
kubectl kustomize deploy/k8s/overlays/dev | kubeconform -strict -ignore-missing-schemas -summary -
```

## Structure map

- `backend/app/`:
  - `api/v1/` — auth, ingest, alerts, incidents, graph, stats, search, rules,
    labels, silences, channels, notifications/notification_admin/notification_defaults,
    groups/group_codes/users/audit, grouping_rules, threshold_overrides,
    retention_config, llm_config, mimir_query_config, saml_config, metrics
  - `core/` — deps, security, visibility (l2 choke point), pagination, config,
    metrics/instruments, locks, rate_limit, envelope
  - `models/` — alerting, delivery, group, grouping, user, audit, mimir, saml,
    llm, maintenance, threshold, notification, base
  - `services/` — incident_service, mimir_sync, threshold, saml_auth, saml_config,
    grouping_config, permissions, audit, maintenance, llm_analysis
  - `providers/` (alertmanager) · `notifications/channels/` (telegram, email, oncall)
    + fanout/delivery/outbox/throttle
  - `workers/` — correlation, notification, maintenance, mimir_sync, llm, metrics_server
  - `integrations/` — base (X-Scope-OrgID), mimir_ruler, alertmanager, oidc, llm, loki
- `frontend/src/`: `pages/` (ops, graph, alerts, incidents, rules-viewer, thresholds,
  silences, groups, users, audit, settings, login, …), `features/`, `components/{ui,common,layout}`,
  `api/{client,queries}.ts`, `locales/{ko,en}.json`
- `deploy/`: `k8s/{base,overlays/{dev,prod}}`, `flux/`
- CI: `.gitlab-ci.yml` (kaniko → registry), `.github/workflows/build.yml`
  (test-backend, test-frontend, validate-manifests, build-and-push)

## Deploy (k8s)

- Deploy an **overlay** (`overlays/dev` or `overlays/prod`), never `base` directly.
  Flux watches this repo → reconciles the prod overlay; image automation bumps the
  prod tag marker.
- `atlas-config` is a **plain ConfigMap** (`base/atlas-config.yaml`) referenced by
  the static name `atlas-config` via `envFrom` — **no configMapGenerator, no hash**.
  Per-env `MIMIR_*` endpoints come from each overlay's `atlas-config-patch.yaml`
  (strategic merge); host-bearing keys (CORS/FRONTEND/APP_ENV/COOKIE_SECURE) from
  the overlay JSON6902 patch. Tradeoff: editing the ConfigMap does **not** auto-roll
  pods → `kubectl rollout restart deployment -n atlas`.
- Pods (all from the backend image): backend + workers correlation / notification /
  maintenance / **mimir-sync** / llm; frontend image = frontend.
- `prometheus-rules.yaml` (PrometheusRule CRD) is kept out of the kustomization so
  `kubeconform -strict` stays green — apply it separately.

## Environment caveats (cloud session)

- No Docker daemon. Real PG: `service postgresql start` (user/db `atlas`/`atlas`).
- Playwright: `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, import from
  `/opt/node22/lib/node_modules/playwright/index.mjs`. Korean default locale →
  assert on data values or Korean text.
- jsdelivr blocked; GitHub releases reachable (kustomize/kubeconform/kubeconform downloads OK).
- Push only to the session's designated feature branch; open one PR per change set, base `main`.

## Migrations (current head: 0009)

| rev | what |
|---|---|
| 0001_imp_baseline | metadata baseline (pinned; pre-creates current schema on fresh DB) |
| 0002_mimir_cache | mimir_rules + mimir_silences |
| 0003_drop_rule_catalog | drop the old PromQL-querying rule catalog |
| 0004_notif_incident_nullable | notifications.incident_id nullable + ON DELETE SET NULL |
| 0005_per_group_channels | group_channels + notification dedup by recipient_address; drop global notification_settings |
| 0006_group_labels | groups.labels (metadata tags) |
| 0007_mimir_query_config | label-query lookback config |
| 0008_saml_config | SAML SP config |
| 0009_saml_user_fields | users.saml_uid + display_name; auth_provider enum += saml |

## Recent change log (merged, newest first)

- **SAML SSO** (admin config + login/ACS + JIT viewer; offline-tested with signed
  fixtures + a live Chromium settings check). OIDC kept; `memberOf` deferred.
- **mimir_query_config** — DB-managed label-query lookback (default 1h) + 502→upstream-status fix.
- **kustomize config refactor** — plain `atlas-config` ConfigMap + per-env `MIMIR_*` patch (no generator/hash).
- **IMP overhaul** — no-PromQL threshold UX, label-based querying, Mimir read-cache
  + sync worker, per-group notification channels, incident-lifecycle (delete/
  detach/auto-resolve), incident-centric swimlane graph, Manage/Settings reorg,
  numbered pagination, admin password reset. Tenancy removed in favor of l2 visibility.
