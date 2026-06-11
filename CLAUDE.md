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

## Already done (do not redo)

All 12 spec phases implemented: models/migration, auth (local+OIDC)+RBAC, integrations,
full REST API, sync worker, 11 frontend screens, 44 tests, k8s + GitLab CI + Flux.
Headless-browser E2E verified the main flows (login / rule CRUD / emergency apply / audit log /
dark mode / mobile).
