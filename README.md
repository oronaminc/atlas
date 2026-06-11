# Atlas — Observability Alert Management Platform

Web UI + REST API for managing alert rules (per server / user / group) on top of an
existing Alloy + Mimir + Mimir Alertmanager + Loki + Tempo + Grafana stack.

- **The DB (PostgreSQL) is the source of truth for rules** — a background worker syncs them to the Mimir Ruler API
- Emergency direct-apply mode + full audit logging
- Every Mimir/Alertmanager/Loki/Tempo request carries `X-Scope-OrgID: system` automatically

## Stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2 |
| DB/Cache | PostgreSQL 16, Redis 7 |
| Frontend | React 18 + TypeScript + Vite, TanStack Query, React Router v6, Tailwind, shadcn/ui |
| Auth     | OIDC (SSO) + local ID/PW, JWT (access 15m / refresh 7d httpOnly cookie) |

## Quick start (docker)

```bash
cp .env.example .env        # fill in FERNET_KEY, SECRET_KEY, etc.
docker compose up --build
# backend:  http://localhost:8000  (OpenAPI: /docs)
# frontend: http://localhost:5173
```

Create the first admin account:

```bash
cd backend
uv run python scripts/create_admin.py admin@example.com admin <password>
# (docker: docker compose exec backend python scripts/create_admin.py ...)
```

## Kubernetes deployment

### Image builds (CI)

`.github/workflows/build.yml` runs on every main push / `v*` tag:
1. backend tests+lint, frontend typecheck+build
2. builds and pushes both images to GHCR:
   - `ghcr.io/oronaminc/atlas/backend` (`latest`, `sha-...`, semver tags)
   - `ghcr.io/oronaminc/atlas/frontend`
3. renders kustomize manifests + validates with kubeconform

Manual build:

```bash
docker build -t ghcr.io/oronaminc/atlas/backend:v0.1.0 ./backend
docker build -t ghcr.io/oronaminc/atlas/frontend:v0.1.0 ./frontend
docker push ghcr.io/oronaminc/atlas/backend:v0.1.0
docker push ghcr.io/oronaminc/atlas/frontend:v0.1.0
```

### Internal-network deployment (GitLab CI + Flux CD)

Pipeline when the final target is an internal k8s cluster:

```
MR/main push → GitLab CI (.gitlab-ci.yml)
  test:  backend pytest+ruff+black / frontend lint+build
  build: kaniko image build → GitLab container registry
         tags: main-<pipeline_iid>-<sha> (main) / vX.Y.Z (git tag)
  validate: kustomize render check
      ↓
Flux (deploy/flux/, applied to flux-system)
  ImageRepository/ImagePolicy: poll registry, pick newest iid tag
  ImageUpdateAutomation: commits new tags to markers in deploy/k8s/overlays/prod
  GitRepository + Kustomization: reconciles the prod overlay (prune + health checks)
```

Setup order:
1. Replace internal mirror endpoints in `.gitlab-ci.yml` variables (PYTHON_IMAGE etc., PyPI/npm)
2. Replace registry path / host in `deploy/k8s/overlays/prod/kustomization.yaml`
3. Replace repo URL / registry path in `deploy/flux/*.yaml`, then `kubectl apply -k deploy/flux`
   (details and secret prep: `deploy/flux/README.md`)
4. Never commit `atlas-secrets` in plaintext — use SOPS/SealedSecrets or create it manually in-cluster

### Manifests (kustomize)

```
deploy/k8s/
  base/            # Namespace, ConfigMap, backend (+migrate initContainer),
                   # worker, frontend, Service, Ingress
  overlays/dev/    # + in-cluster postgres/redis, dev secret, replicas=1
  overlays/prod/   # internal registry images + Flux imagepolicy markers
```

Production deploy:

```bash
# 1) Point the ConfigMap MIMIR_*_URL values at the existing observability stack
# 2) Create the secret (see deploy/k8s/base/secret.example.yaml)
kubectl -n atlas create secret generic atlas-secrets --from-literal=SECRET_KEY=... ...
# 3) Pin image tags and apply
cd deploy/k8s/base && kustomize edit set image \
  ghcr.io/oronaminc/atlas/backend=ghcr.io/oronaminc/atlas/backend:v0.1.0 \
  ghcr.io/oronaminc/atlas/frontend=ghcr.io/oronaminc/atlas/frontend:v0.1.0
kubectl apply -k deploy/k8s/base
# 4) First admin
kubectl -n atlas exec deploy/atlas-backend -- python scripts/create_admin.py admin@example.com admin <pw>
```

- DB migrations run automatically at pod start via the backend `migrate` initContainer (`alembic upgrade head`)
- The frontend nginx upstream is injected via the `BACKEND_ORIGIN` env var (k8s: `http://atlas-backend:8000`)
- Ingress: `/api` → backend, `/` → frontend (adjust host per environment)

### Local k8s testing (kind)

```bash
# requires: docker, kind, kubectl
./deploy/kind-up.sh     # create cluster → build/load images → deploy dev overlay → wait for rollout
kubectl -n atlas exec deploy/atlas-backend -- python scripts/create_admin.py admin@example.com admin <pw>
kubectl -n atlas port-forward svc/atlas-frontend 8080:80
# open http://localhost:8080 in Chrome
```

To validate manifests without a cluster:

```bash
kubectl kustomize deploy/k8s/overlays/dev | kubeconform -strict -summary -
```

## Local development

### Backend (uv)

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload          # API server
uv run python -m app.workers.sync_worker      # sync worker (separate terminal)
uv run pytest                                 # tests
uv run ruff check . && uv run black --check . # lint
```

### Frontend (pnpm)

```bash
cd frontend
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # typecheck + production build
pnpm lint
```

## Directory layout

```
backend/app/
  api/v1/        # routers
  core/          # config, security, deps
  models/        # SQLAlchemy
  schemas/       # Pydantic
  services/      # business logic
  integrations/  # base.py, mimir_ruler.py, alertmanager.py, loki.py, oidc.py
  workers/       # sync worker
frontend/src/
  {pages,components,features,lib,hooks,api,types}
deploy/
  k8s/{base,overlays/{dev,prod}}   # kustomize
  flux/                            # Flux CD (GitOps)
```

## Run log (how each build phase was verified)

1. **Scaffolding**: `docker compose config` validates the compose file.
2. **Frontend base**: `cd frontend && pnpm install && pnpm build`; check AppLayout renders via `pnpm dev`.
3. **DB models + migration**: `cd backend && uv run alembic upgrade head`.
4. **Auth + RBAC**: `uv run pytest tests/test_auth.py`.
5. **Integrations**: `uv run pytest tests/test_integrations.py` — verifies X-Scope-OrgID injection.
6. **Users/Groups/Servers CRUD**: `uv run pytest tests/test_users_groups.py tests/test_servers.py`.
7. **Alert Rules CRUD + validate/test**: `uv run pytest tests/test_rules.py`.
8. **Rule Groups + sync + emergency-apply**: `uv run pytest tests/test_sync.py`.
9. **Notifications**: `uv run pytest tests/test_notifications.py`.
10. **Alerts proxy + dashboard**: `uv run pytest tests/test_alerts.py`.
11. **Frontend screens**: `cd frontend && pnpm build` (keep type errors at 0) + `pnpm lint`.
12. **Wrap-up**: `curl localhost:8000/healthz`, `curl localhost:8000/readyz`, OpenAPI at `/docs`.

## Key design notes

- **X-Scope-OrgID**: injected exactly once in `make_client()` in `backend/app/integrations/base.py`.
  Every Mimir/Alertmanager/Loki client inherits it; never set it on individual calls.
- **Sync flow**: rule/rule-group mutation → `sync_state(ruler)=pending` → worker (30s) serializes
  rule groups to Prometheus YAML → checksum compare → PUT only changes to the Ruler. Redis lock
  prevents duplicate syncs.
- **Emergency apply**: `POST /api/v1/rules/emergency-apply` — validate → push immediately to the
  `emergency` namespace → persist to DB → audit(emergency=true). In the UI: rule list ⋮ menu,
  requires a reason.
- **Receiver secrets**: url/api_key etc. in config are Fernet-encrypted at rest and masked in API responses.
- **RBAC**: global roles (admin/editor/viewer) + group manager. scope=user rules: owner/admin only.
