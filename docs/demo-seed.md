# Demo / UI-stress seed

`backend/scripts/seed_ui_stress.py` populates Atlas with realistic-volume
**demo** data for manually exercising the UI (incidents, /graph, servers,
mutes, thresholds). It is idempotent and fully removable.

> ⚠️ **DEMO DATA — never run against prod.** It writes fabricated
> incidents/servers/alerts. Every row it creates is `demo`-prefixed and it only
> ever touches those prefixes, but it is a demo tool: run it against dev or a
> local sandbox only.

## a. What it creates

| Kind | Count | Notes |
|---|---|---|
| Server groups | 6 | `demo-web-tier`, `demo-api-tier`, `demo-db-tier`, `demo-cache-tier`, `demo-batch-tier`, `demo-infra-tier` |
| Servers | 50 | `demo-<tier>-NN.sktelecom.com`, `cmdb_ci=DEMO-SVC1000NN`, cmdb_* labels **incl. ip** (`cmdb_ip` + `instance`) |
| Incidents | 27 | incl. **1× 20-alert**, **1× 18-label** alert, **1× rich nested-JSON timeline**; varied severity/status over the last 24h |
| Rule catalog | 10 | `Demo*` alertnames, half configured (comparator/unit/value_query), half pass-through |
| Threshold overrides | 7 | server + group tiers; server targets use real demo `cmdb_ci` |
| Notification mutes | 4 | server / group / all + alertname wildcards |

All rows are `tenant_id=NULL` so the HQ admin sees them.

**Demo markers (everything is greppable / safe to remove):**
`cmdb_ci` → `DEMO-SVC…` · group name & hostname → `demo-…` · alertname →
`Demo…` · `alert_events.fingerprint` → `demo-…` · incident `group_key` →
`host=demo-…`.

## b. How to run

### Dev cluster (exec into the backend pod)
The backend image bundles the script and already has `DATABASE_URL` etc. from
the configmap/secret, so no env wiring is needed inside the pod.

```bash
# 1. find a running backend pod
kubectl -n atlas get pods -l app=atlas-backend

# 2. (first time only) make sure migrations are applied + an admin exists
kubectl -n atlas exec deploy/atlas-backend -- python -m alembic upgrade head
kubectl -n atlas exec deploy/atlas-backend -- \
  python scripts/create_admin.py admin@sktelecom.com admin '<password>'

# 3. seed (idempotent — safe to re-run)
kubectl -n atlas exec deploy/atlas-backend -- python scripts/seed_ui_stress.py
```

> If the image entrypoint runs from `/app`, the script path is
> `scripts/seed_ui_stress.py` (cwd `/app`). Adjust to `/app/scripts/...` if your
> working dir differs. `alembic`/`create_admin.py` are the same as a normal
> bootstrap — skip step 2 if the dev DB is already migrated with an admin.

### Local sandbox
```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:////tmp/atlas.db" \
       SECRET_KEY=dev-secret-key-change-me-0123456789 \
       FERNET_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
uv run alembic upgrade head
uv run python scripts/create_admin.py admin@example.com admin password123
uv run python scripts/seed_ui_stress.py
```

## c. Clear / reset

The script is **idempotent**: a normal run first removes any prior demo data,
then reseeds — so re-running never duplicates. To remove demo data without
reseeding:

```bash
# dev
kubectl -n atlas exec deploy/atlas-backend -- python scripts/seed_ui_stress.py --clear
# local
uv run python scripts/seed_ui_stress.py --clear
```

`--clear` (and the clear step of a normal run) deletes **only** demo-prefixed
rows — real incidents/servers/rules are never touched. It prints the per-table
delete counts.

## d. Safety

- DEMO only. Do **not** run against prod.
- Idempotent + prefix-scoped: re-runnable, and cleanup can never remove
  non-demo rows.
- All demo rows carry the prefixes above; if you ever need to audit what exists,
  `SELECT * FROM servers WHERE cmdb_ci LIKE 'DEMO-SVC%'` (and the analogous
  `demo-%` / `Demo%` filters) lists it.
