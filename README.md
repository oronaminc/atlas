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
11. **Frontend 화면**: `cd frontend && pnpm build` (화면 추가마다 타입에러 0 유지).
12. **마무리**: `curl localhost:8000/healthz`, `curl localhost:8000/readyz`.
