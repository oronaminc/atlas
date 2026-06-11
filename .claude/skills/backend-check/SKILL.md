---
name: backend-check
description: Run tests+lint+migration checks after backend changes. Always use after modifying files under backend/.
---

# Backend verification

Run in order after any backend/ change. All must pass before committing.

```bash
cd backend
uv run pytest -q                  # 44+ tests, 0 failures required
uv run ruff check . && uv run black --check .
```

If models/migrations were touched, additionally:

```bash
rm -f /tmp/_mig.db && DATABASE_URL="sqlite+aiosqlite:////tmp/_mig.db" uv run alembic upgrade head && rm -f /tmp/_mig.db
```

## Gotchas

- New migrations must use explicit alembic ops (do NOT use metadata.create_all like 0001).
- Tests run on SQLite — PG-only types (JSONB etc.) must use the `app/models/base.py::JsonType` variant pattern.
- Beware lazy loads in async sessions (MissingGreenlet): eager-load relationships with selectinload
  when needed. (Precedent: `load_group()` in the rule_groups router.)
- New external API calls go through `integrations/base.py` — never re-inject X-Scope-OrgID.
- New write endpoints require record_audit + mark_ruler_pending (if rule-related).
