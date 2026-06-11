---
name: e2e-browser
description: 풀스택(backend+frontend)을 띄우고 헤드리스 Chromium으로 실제 UI 플로우(로그인→룰 CRUD→긴급적용→감사로그)를 검증. UI 동작 확인이나 사용자가 "브라우저로 테스트"를 요청할 때 사용.
---

# 브라우저 E2E 검증

이 디렉터리의 `e2e.mjs`(Playwright 시나리오)와 `fake_ruler.py`(Mimir Ruler 스텁)는
검증 완료된 스크립트다. 순서대로:

## 1. 스택 기동 (각각 백그라운드)

```bash
# Ruler 스텁 (수신 요청을 /tmp/fake_ruler_requests.jsonl에 기록)
python3 .claude/skills/e2e-browser/fake_ruler.py &

# Backend (SQLite, 프로세스 kill 후 재시작하면 rate limiter도 초기화됨)
cd backend
export DATABASE_URL="sqlite+aiosqlite:////tmp/atlas_e2e.db" \
  SECRET_KEY="e2e-test-secret-key-with-enough-length-123456" \
  FERNET_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  MIMIR_RULER_URL="http://127.0.0.1:18080/prometheus/config/v1/rules" \
  MIMIR_ALERTMANAGER_URL="http://127.0.0.1:18081"
rm -f /tmp/atlas_e2e.db && uv run alembic upgrade head
uv run python scripts/create_admin.py admin@example.com admin password123
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &   # nohup+disown 권장

# Frontend
cd ../frontend && pnpm dev --host 127.0.0.1 --port 5173 &
```

기동 확인: `curl -s 127.0.0.1:8000/readyz` 와 `curl -sI 127.0.0.1:5173`.

## 2. E2E 실행

```bash
mkdir -p /tmp/shots
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node .claude/skills/e2e-browser/e2e.mjs
```

성공 시 `E2E_OK` 출력 + `/tmp/shots/*.png` 16장. 실패 시 `99-failure.png` 확인.

## 3. 헤더 검증 (X-Scope-OrgID)

```bash
cat /tmp/fake_ruler_requests.jsonl   # x_scope_orgid == "system" 이어야 함
```

## 함정 (전부 실제로 겪은 것)

- **DB는 반드시 매 실행 전 삭제** — 이전 실행의 web-01/HighCPUUsage가 남으면 409로 다이얼로그가 안 닫혀 실패.
- 로그인 5회 실패 시 rate limit(429) — backend 프로세스 재시작으로 초기화.
- playwright는 ESM 절대경로 import (`/opt/node22/lib/node_modules/playwright/index.mjs`).
- 브라우저는 `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` (이미 설치돼 있음, install 불필요).
- 끝나면 `pkill -f uvicorn; pkill -f fake_ruler; pkill -f vite` 로 정리.
