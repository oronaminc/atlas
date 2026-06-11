# Atlas — Observability Alert Management Platform

Alloy+Mimir+Loki+Tempo+Grafana 스택 위 알림 룰 관리 웹 (FastAPI + React).
**DB(PostgreSQL)가 룰의 source of truth** → sync worker가 Mimir Ruler로 동기화.

## 절대 규칙 (스펙 고정)

- 모든 Mimir/Alertmanager/Loki 호출에 `X-Scope-OrgID: system` 헤더.
  **`backend/app/integrations/base.py`의 `make_client()`에서 1회만 주입** — 개별 호출에 중복 작성 금지.
- 기술 스택 변경 금지: Python 3.12/FastAPI/SQLAlchemy 2.0 async/Alembic, React 18/Vite/Tailwind v3/shadcn, uv + pnpm.
- 응답은 envelope `{data, error, meta}`, 페이지네이션은 cursor 기반.
- 모든 쓰기 작업은 `services/audit.py::record_audit` 기록. 긴급 적용은 `emergency=true`.
- secret은 env로만. receiver config의 url/api_key 등은 Fernet 암호화 저장 + API 응답 마스킹.
- 프론트 화면 추가/수정 시마다 `pnpm build` 통과 + 타입에러 0 유지.
- Monaco는 로컬 번들 (`src/lib/monaco.ts`) — CDN 로드 금지(폐쇄망).

## 구조 (요약)

- `backend/app/`: `api/v1/`(라우터) `core/`(config·security·deps·pagination) `models/` `schemas/`
  `services/`(permissions·rule_sync·rule_validate·audit) `integrations/` `workers/sync_worker.py`
- `frontend/src/`: `pages/` `components/{ui,common,layout}` `features/` `api/`(client.ts·queries.ts) `hooks/` `lib/`
- `deploy/`: `k8s/{base,overlays/{dev,prod}}`(kustomize) `flux/`(CD) `kind-up.sh`
- CI: `.gitlab-ci.yml`(내부망 본선: kaniko→GitLab registry), `.github/workflows/build.yml`(GitHub용)

## RBAC 요약

admin=전부 / editor=자기 group·server 스코프 룰 CRUD+긴급적용 / viewer=읽기 /
group manager=그룹 멤버·그룹스코프 룰 / scope=user 룰은 본인+admin만 / global 룰 쓰기는 admin만.

## 검증 명령 (수정 후 반드시)

- backend: `cd backend && uv run pytest -q && uv run ruff check . && uv run black --check .`
- frontend: `cd frontend && pnpm build && pnpm lint`
- k8s 매니페스트: `kubectl kustomize deploy/k8s/overlays/dev | kubeconform -strict -summary -`
- 자세한 절차는 `.claude/skills/` 의 스킬 사용 (backend-check, frontend-check, e2e-browser, k8s-validate)

## 배포 파이프라인 (사용자 목표)

내부망 k8s가 최종 타깃. GitLab CI(test→kaniko build→registry, 태그 `main-<iid>-<sha>`)
→ Flux CD(`deploy/flux/`, image automation이 prod overlay 태그 마커에 자동 커밋).
내부 미러 주소는 `.gitlab-ci.yml` variables로 교체. atlas-secrets는 git 평문 금지(SOPS/SealedSecrets).

## 환경 주의사항 (이 클라우드 세션)

- Docker 데몬 없음 → 이미지 빌드/kind 불가. 테스트는 SQLite(aiosqlite)로.
- Playwright 브라우저는 `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`, 라이브러리는
  `import ... from "/opt/node22/lib/node_modules/playwright/index.mjs"`.
- jsdelivr 등 일부 CDN 차단됨.
- 작업 브랜치: `claude/epic-dijkstra-mgq4oa` (push는 이 브랜치로만).

## 이미 끝난 단계 (재작업 금지)

스펙 11절 1–12단계 전부 구현 완료: 모델/마이그레이션, auth(로컬+OIDC)+RBAC, integrations,
전체 REST API, sync worker, 프론트 11개 화면, 테스트 44개, k8s+GitLab CI+Flux.
헤드리스 브라우저 E2E로 주요 플로우 검증 완료 (로그인/룰 CRUD/긴급적용/감사로그/다크모드/모바일).
