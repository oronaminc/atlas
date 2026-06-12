---
name: tdd-discipline
description: The test-first + concurrency-proof workflow this repo uses for any new backend feature. Use when implementing a new feature/subsystem or anything touching worker claim/queue logic.
---

# TDD + concurrency discipline

The contract used for the correlation engine, notification delivery, and
dashboards. Follow it for new features.

## Workflow

1. **Tests first, committed red.** Pin module paths, function signatures, API
   routes, and RBAC in the tests; show the user; get approval before impl.
   Helpers live next to tests (`tests/<area>/helpers.py`).
2. **Implement** in dependency order: migration → models → services → routers →
   workers → UI. New migrations = explicit alembic ops (0001 pre-creates enums
   and current columns on fresh DBs — guard with `checkfirst`/inspector, see
   0002/0003).
3. **Concurrency proof is mandatory** for anything multiple worker replicas touch:
   - SQLite tier (`tests/notifications/test_concurrency.py` pattern): file-backed
     DB, two sessions = two pods, interleaved claims → disjoint sets, lease-expiry
     crash recovery. Proves the CAS logic everywhere.
   - Real-PG tier (`tests/pg/`, gated on `ATLAS_PG_TEST_URL`): N asyncio workers
     on distinct connections racing the same rows → exactly-once + advisory-lock
     guarantees. Run locally: `service postgresql start` (this env) or
     `./scripts/pg_concurrency_test.sh` (compose). CI: `test-pg-concurrency` job.
   - Claim pattern to copy: candidates select (+`FOR UPDATE SKIP LOCKED` on PG)
     → per-row CAS UPDATE with the same guard + `synchronize_session=False`
     → re-select with `populate_existing=True`. Completion clears `claimed_at`.
4. **Green gate** before reporting done:
   ```bash
   cd backend && uv run pytest -q && uv run ruff check . && uv run black --check .
   ATLAS_PG_TEST_URL=... uv run pytest tests/pg -q        # if claim logic touched
   rm -f /tmp/_m.db && DATABASE_URL=sqlite+aiosqlite:////tmp/_m.db uv run alembic upgrade head && \
     DATABASE_URL=sqlite+aiosqlite:////tmp/_m.db uv run alembic downgrade base   # if migration touched
   cd ../frontend && pnpm build && pnpm lint               # if UI touched
   ```
5. UI features additionally get a browser e2e pass with screenshots
   (e2e-browser skill; seed via `scripts/seed_demo.py`).

## Recurring pitfalls (all hit in this repo)

- ORM CAS updates: default `synchronize_session` evaluates criteria in Python →
  naive-vs-aware datetime TypeError on SQLite. Always `synchronize_session=False`.
- SQLite drops tzinfo → use `AwareDateTime` for columns compared in Python.
- Async lazy loads (`MissingGreenlet`) → eager-load (`selectinload`) or re-select;
  never touch unloaded relationships after `db.refresh`.
- Unique-constraint seeds: distinct users/incidents per outbox row in fixtures.
