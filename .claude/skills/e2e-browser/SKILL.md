---
name: e2e-browser
description: Start the full stack (backend+frontend) and verify real UI flows (login → rule CRUD → emergency apply → audit log) with headless Chromium. Use for UI verification or when the user asks for browser testing.
---

# Browser E2E verification

`e2e.mjs` (Playwright scenario) and `fake_ruler.py` (Mimir Ruler stub) in this directory are
proven scripts. Note: e2e.mjs selectors match the Korean UI strings (ko is the default locale) —
do not translate them. Steps:

## 1. Start the stack (each in background)

```bash
# Ruler stub (records incoming requests to /tmp/fake_ruler_requests.jsonl)
python3 .claude/skills/e2e-browser/fake_ruler.py &

# Backend (SQLite; killing and restarting the process also resets the rate limiter)
cd backend
export DATABASE_URL="sqlite+aiosqlite:////tmp/atlas_e2e.db" \
  SECRET_KEY="e2e-test-secret-key-with-enough-length-123456" \
  FERNET_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
  MIMIR_RULER_URL="http://127.0.0.1:18080/prometheus/config/v1/rules" \
  MIMIR_ALERTMANAGER_URL="http://127.0.0.1:18081"
rm -f /tmp/atlas_e2e.db && uv run alembic upgrade head
uv run python scripts/create_admin.py admin@example.com admin password123
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &   # prefer nohup+disown

# Frontend
cd ../frontend && pnpm dev --host 127.0.0.1 --port 5173 &
```

Health check: `curl -s 127.0.0.1:8000/readyz` and `curl -sI 127.0.0.1:5173`.

## 2. Run E2E

```bash
mkdir -p /tmp/shots
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node .claude/skills/e2e-browser/e2e.mjs
```

Success prints `E2E_OK` + 16 screenshots in `/tmp/shots/`. On failure check `99-failure.png`.

For the /graph swimlane view (requires seed_demo data):

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node .claude/skills/e2e-browser/graph_e2e.mjs
```

Success prints `GRAPH_E2E_OK` + 4 screenshots (full view, same_name hover
highlight, incident side panel, expanded lanes).

For RBAC (3 roles) + incident suppression (requires seed_demo + editor/viewer
users + one receiver + a freshly correlated incident — see the script header
for the exact curl/python prep):

```bash
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node .claude/skills/e2e-browser/rbac_suppress_e2e.mjs
```

Success prints `RBAC_SUPPRESS_E2E_OK` + screenshots per role and per
suppression step.

## 3. Header verification (X-Scope-OrgID)

```bash
cat /tmp/fake_ruler_requests.jsonl   # x_scope_orgid must be "system"
```

Seed richer demo data (ops dashboard / swimlane graph) with
`uv run python scripts/seed_demo.py` after create_admin (includes a correlated
burst within the 900s window and 10+ hosts for the /graph lane expander).

## Pitfalls (all actually encountered)

- **Always delete the DB before each run** — leftover web-01/HighCPUUsage from a previous run
  causes 409s that keep dialogs open and fail the run.
- 5 failed logins trigger rate limiting (429) — restart the backend process to reset.
- Playwright must be imported via absolute ESM path (`/opt/node22/lib/node_modules/playwright/index.mjs`).
- Browsers live at `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` (pre-installed; no install needed).
- Clean up afterwards: kill uvicorn/fake_ruler/vite — but NOT with bare
  `pkill -f uvicorn` from this harness: the pattern matches the wrapping
  bash -c snapshot line and kills your own shell (exit 144). Use
  `pgrep -f "uvicorn[ ]app" | xargs -r kill` or kill by port.
- The login rate limiter (5/300s per IP+email) also counts successful logins;
  repeated e2e runs against the same backend will 429 — restart the backend
  process between runs to reset it.
