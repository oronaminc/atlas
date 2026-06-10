# Atlas — Observability Alert Management Platform

Alloy + Mimir + Mimir Alertmanager + Loki + Tempo + Grafana 스택 위에서
서버별/사용자별/그룹별 Alert 룰을 관리하는 웹사이트 + REST API.

- **DB(PostgreSQL)가 룰의 source of truth** — 백그라운드 워커가 Mimir Ruler API로 동기화
- 긴급 직접수정 모드(emergency apply) + 전면 audit log
- 모든 Mimir/Alertmanager/Loki/Tempo 요청에 `X-Scope-OrgID: system` 헤더 자동 주입

## Stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2 |
| DB/Cache | PostgreSQL 16, Redis 7 |
| Frontend | React 18 + TypeScript + Vite, TanStack Query, React Router v6, Tailwind, shadcn/ui |
| Auth     | OIDC(SSO) + 로컬 ID/PW, JWT(access 15m / refresh 7d httpOnly cookie) |

## Quick start (docker)

```bash
cp .env.example .env        # FERNET_KEY, SECRET_KEY 등 채우기
docker compose up --build
# backend:  http://localhost:8000  (OpenAPI: /docs)
# frontend: http://localhost:5173
```

최초 admin 계정 생성:

```bash
cd backend
uv run python scripts/create_admin.py admin@example.com admin <password>
# (docker: docker compose exec backend python scripts/create_admin.py ...)
```

## Kubernetes 배포

### 이미지 빌드 (CI)

`.github/workflows/build.yml` 이 main push / `v*` 태그마다:
1. backend 테스트+린트, frontend 타입체크+빌드
2. 두 이미지를 GHCR로 빌드/푸시:
   - `ghcr.io/oronaminc/atlas/backend` (`latest`, `sha-...`, semver 태그)
   - `ghcr.io/oronaminc/atlas/frontend`
3. kustomize 매니페스트 렌더링 + kubeconform 스키마 검증

수동 빌드:

```bash
docker build -t ghcr.io/oronaminc/atlas/backend:v0.1.0 ./backend
docker build -t ghcr.io/oronaminc/atlas/frontend:v0.1.0 ./frontend
docker push ghcr.io/oronaminc/atlas/backend:v0.1.0
docker push ghcr.io/oronaminc/atlas/frontend:v0.1.0
```

### 매니페스트 (kustomize)

```
deploy/k8s/
  base/            # Namespace, ConfigMap, backend(+migrate initContainer),
                   # worker, frontend, Service, Ingress
  overlays/dev/    # + in-cluster postgres/redis, dev secret, replicas=1
```

운영 배포:

```bash
# 1) ConfigMap의 MIMIR_*_URL 을 기존 관측 스택 주소로 수정
# 2) secret 생성 (deploy/k8s/base/secret.example.yaml 의 명령 참고)
kubectl -n atlas create secret generic atlas-secrets --from-literal=SECRET_KEY=... ...
# 3) 이미지 태그 고정 후 적용
cd deploy/k8s/base && kustomize edit set image \
  ghcr.io/oronaminc/atlas/backend=ghcr.io/oronaminc/atlas/backend:v0.1.0 \
  ghcr.io/oronaminc/atlas/frontend=ghcr.io/oronaminc/atlas/frontend:v0.1.0
kubectl apply -k deploy/k8s/base
# 4) 최초 admin
kubectl -n atlas exec deploy/atlas-backend -- python scripts/create_admin.py admin@example.com admin <pw>
```

- DB 마이그레이션은 backend Pod의 `migrate` initContainer가 기동 시 자동 실행 (`alembic upgrade head`)
- frontend nginx의 백엔드 주소는 `BACKEND_ORIGIN` 환경변수로 주입 (k8s: `http://atlas-backend:8000`)
- Ingress: `/api` → backend, `/` → frontend (host는 환경에 맞게 수정)

### 로컬에서 k8s 테스트 (kind)

```bash
# 필요: docker, kind, kubectl
./deploy/kind-up.sh     # 클러스터 생성 → 이미지 빌드/로드 → dev 오버레이 배포 → rollout 대기
kubectl -n atlas exec deploy/atlas-backend -- python scripts/create_admin.py admin@example.com admin <pw>
kubectl -n atlas port-forward svc/atlas-frontend 8080:80
# 크롬에서 http://localhost:8080
```

클러스터 없이 매니페스트만 검증하려면:

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
uv run python -m app.workers.sync_worker      # sync worker (별도 터미널)
uv run pytest                                 # tests
uv run ruff check . && uv run black --check . # lint
```

### Frontend (pnpm)

```bash
cd frontend
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # 타입체크 + 프로덕션 빌드
pnpm lint
```

## Directory layout

```
backend/app/
  api/v1/        # 라우터
  core/          # config, security, deps
  models/        # SQLAlchemy
  schemas/       # Pydantic
  services/      # 비즈니스 로직
  integrations/  # base.py, mimir_ruler.py, alertmanager.py, loki.py, oidc.py
  workers/       # sync worker
frontend/src/
  {pages,components,features,lib,hooks,api,types}
```

## Run log (단계별 실행/테스트 방법)

1. **스캐폴딩**: `docker compose config` 로 compose 유효성 확인.
2. **Frontend 베이스**: `cd frontend && pnpm install && pnpm build` — AppLayout(사이드바+상단바) 렌더 확인은 `pnpm dev`.
3. **DB 모델 + 마이그레이션**: `cd backend && uv run alembic upgrade head`.
4. **Auth + RBAC**: `uv run pytest tests/test_auth.py`.
5. **Integrations**: `uv run pytest tests/test_integrations.py` — X-Scope-OrgID 헤더 주입 검증.
6. **Users/Groups/Servers CRUD**: `uv run pytest tests/test_users_groups.py tests/test_servers.py`.
7. **Alert Rules CRUD + validate/test**: `uv run pytest tests/test_rules.py`.
8. **Rule Groups + sync + emergency-apply**: `uv run pytest tests/test_sync.py`.
9. **Notifications**: `uv run pytest tests/test_notifications.py`.
10. **Alerts 프록시 + 대시보드**: `uv run pytest tests/test_alerts.py`.
11. **Frontend 화면**: `cd frontend && pnpm build` (화면 추가마다 타입에러 0 유지) + `pnpm lint`.
12. **마무리**: `curl localhost:8000/healthz`, `curl localhost:8000/readyz`, OpenAPI는 `/docs`.

## 주요 설계 노트

- **X-Scope-OrgID**: `backend/app/integrations/base.py`의 `make_client()`에서 단 한 번 주입.
  모든 Mimir/Alertmanager/Loki 클라이언트가 이를 상속하며, 개별 호출에는 작성하지 않는다.
- **동기화 흐름**: 룰/룰그룹 변경 → `sync_state(ruler)=pending` → 워커(30s)가 rule group을
  Prometheus YAML로 직렬화 → checksum 비교 → 변경분만 Ruler PUT. Redis lock으로 중복 방지.
- **긴급 적용**: `POST /api/v1/rules/emergency-apply` — 검증 → `emergency` namespace로 즉시
  push → DB 반영 → audit(emergency=true). UI의 룰 목록 ⋮ 메뉴에서 사유 입력 후 실행.
- **Receiver secret**: config의 url/api_key 등은 Fernet 암호화 저장, API 응답에서는 마스킹.
- **RBAC**: 전역 role(admin/editor/viewer) + group manager. scope=user 룰은 본인/admin만.
