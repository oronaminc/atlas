# Atlas configuration & env-var reference

How to change Atlas runtime config safely, and the full list of settings the
backend reads. Source of truth for the settings list: `backend/app/core/config.py`
(`Settings`, pydantic-settings — every field is read from an env var of the same
name at process start).

---

## 1. The two change categories (read this first)

**Why the distinction exists:** pydantic reads env vars *at runtime* when the
process boots. So any setting **that already exists in the deployed image** is
changed purely by editing the env (ConfigMap/Secret) and restarting the pod — no
rebuild. A setting only needs a rebuild when it is **brand-new in code** and the
running image predates it: the ConfigMap key sits inert because no code in the
image reads it yet (`extra="ignore"` silently drops unknown keys).

### (a) ConfigMap-only — change + restart, takes effect immediately, NO rebuild
Edit the ConfigMap (or Secret) patch, Flux applies, restart the pod. This is the
normal case — **every** setting already shipped in the image is here. Examples:
`MIMIR_*_URL`, `LOKI_URL`, `TEMPO_URL`, `GRAFANA_URL`, `ROOT_PATH`, `APP_ENV`,
`SYNC_INTERVAL_SECONDS`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `CORS_ORIGINS`, …

### (b) Needs rebuild — new code setting the deployed image doesn't know yet
The setting was just added in code; until the backend image is rebuilt with the
code that references it, the ConfigMap key does nothing.

**Currently in this state (added, not yet in a deployed image):**
- `COOKIE_SECURE`
- `COOKIE_SAMESITE`

Once the image carrying these ships, they graduate to category (a) and are
ConfigMap-only forever after. (Nothing is *permanently* "needs rebuild" — it's a
temporary state of any new setting between code-merge and image-deploy.)

> Secrets (`SECRET_KEY`, `FERNET_KEY`, `DATABASE_URL`, `INGEST_API_KEY`,
> `OIDC_*`, `SMTP_PASSWORD`) live in the `atlas-secrets` Secret, **not** the
> ConfigMap — but they follow the same runtime-read rule: change + restart, no
> rebuild.

---

## 2. Render-verify — the single source of truth

A config value only reaches the cluster if it appears in the rendered ConfigMap.
If a key is **not** in this output, it will **not** reach the cluster (the
patch-not-applying trap — a patch in a sub-folder kustomization never reaches a
base resource; per-env patches must live in the overlay's **top-level**
`kustomization.yaml`).

```bash
# atlas-gitops
kubectl kustomize infrastructure/dev | grep -A40 "name: atlas-config"
kubectl kustomize infrastructure/prd | grep -A40 "name: atlas-config"

# app repo (deploy/k8s)
kubectl kustomize deploy/k8s/overlays/dev  | grep -A40 "name: atlas-config"
kubectl kustomize deploy/k8s/overlays/prod | grep -A40 "name: atlas-config"
```

Grep for the specific key to confirm: `... | grep COOKIE_SECURE` must print it.

---

## 3. Step-by-step

### Scenario A — change a ConfigMap-only var (e.g. a MIMIR URL)
1. Edit the ConfigMap patch in the overlay's **top-level** kustomization:
   `atlas-gitops/infrastructure/{dev,prd}/kustomization.yaml` → the
   `patches:` block targeting `kind: ConfigMap, name: atlas-config`. (Mirror in
   the app repo: `deploy/k8s/overlays/{dev,prod}/kustomization.yaml`.)
2. Render-verify: `kubectl kustomize infrastructure/dev | grep -A40 "name: atlas-config"`
   — confirm the new value is present.
3. Commit + push → Flux reconciles and applies the ConfigMap.
4. **Pods roll automatically** — see §6. `atlas-config` is a `configMapGenerator`,
   so a content change produces a new hash-suffixed name → new ReplicaSet → all
   pods that reference it (backend + every worker) restart and re-read env. No
   manual `kubectl rollout restart` needed. (Without the generator, settings are
   read once at boot and a live pod keeps the OLD value until a restart — this is
   the "I changed the ConfigMap but nothing happened" trap.)

### Scenario B — add/change a needs-rebuild var (e.g. `COOKIE_SECURE`)
1. **Code change:** add the field to `Settings` in `backend/app/core/config.py`
   and use it where relevant. Merge to `main`.
2. **CI builds a new image** (GitLab tags `0.1.<pipeline-iid>`).
3. **Bump the image tag** in `atlas-gitops/infrastructure/dev/kustomization.yaml`
   `images:` (dev) — or let Flux ImageUpdateAutomation bump it via the
   `{"$imagepolicy": ...}` marker for prd.
4. **Set the ConfigMap key** (same as Scenario A) in the overlay patch.
5. Render-verify both the image tag and the key.
6. Flux deploys the new image with the new ConfigMap → the setting takes effect.
   (Order is forgiving: the ConfigMap key is harmless on the old image and
   activates the moment the new image rolls.)

---

## 4. Full settings list

Default = the code default in `config.py`. **Store** = where the value belongs in
k8s (`ConfigMap atlas-config` / `Secret atlas-secrets`). All are change+restart,
no rebuild, *except the two new ones flagged ⚠️ until their image ships*.

### App / core
| Var | Controls | Default | Store |
|---|---|---|---|
| `APP_ENV` | Environment label (`dev`/`test`/`prod`); gates secure-by-default branches elsewhere | `dev` | ConfigMap |
| `SECRET_KEY` | JWT signing key (HS256) | `dev-secret-key-change-me` | Secret |
| `FERNET_KEY` | Fernet key for DB-stored token encryption | `""` | Secret |
| `ROOT_PATH` | Subpath prefix for FastAPI (docs/openapi + auth-cookie path); `""` = root | `""` | ConfigMap |
| `DATABASE_URL` | Postgres DSN (asyncpg) | `postgresql+asyncpg://atlas:atlas@localhost:5432/atlas` | Secret |
| `REDIS_URL` | Redis URL (stream wake-up, dedup window, rate limiter) | `redis://localhost:6379/0` | Secret |

### Auth & cookies
| Var | Controls | Default | Store |
|---|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access-JWT lifetime | `15` | ConfigMap |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-cookie lifetime | `7` | ConfigMap |
| `COOKIE_SECURE` ⚠️ | `Secure` flag on refresh/OIDC cookies; **must be `false` over plain HTTP** or the cookie is dropped | `True` | ConfigMap |
| `COOKIE_SAMESITE` ⚠️ | `SameSite` for the refresh cookie (`strict`/`lax`/`none`) | `strict` | ConfigMap |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | Failed-login attempts per window before 429 | `5` | ConfigMap |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit window | `300` | ConfigMap |

### Observability backend URLs (all ConfigMap; per-overlay)
| Var | Controls | Default | Store |
|---|---|---|---|
| `MIMIR_RULER_URL` | Mimir Ruler config API (rule sync target) | `http://mimir:8080/prometheus/config/v1/rules` | ConfigMap |
| `MIMIR_ALERTMANAGER_URL` | Mimir Alertmanager (AM provisioning) | `http://mimir-alertmanager:8080` | ConfigMap |
| `MIMIR_QUERY_URL` | Mimir query (PromQL; threshold value fetch) | `http://mimir:8080/prometheus` | ConfigMap |
| `LOKI_URL` | Loki base | `http://loki:3100` | ConfigMap |
| `TEMPO_URL` | Tempo base | `http://tempo:3200` | ConfigMap |
| `GRAFANA_URL` | Grafana base | `http://grafana:3000` | ConfigMap |

> Current cluster values (dev+prd overlays): gateways on **port 80**, each in its
> own namespace — `mimir-gateway.mimir.svc:80` (fronts ruler+query+AM),
> `loki-gateway.loki.svc:80`, `tempo-gateway.tempo.svc:80`,
> `grafana.grafana.svc:80`. `X-Scope-OrgID` is injected once in
> `integrations/base.py`, not via these URLs.

### Tenancy / ingest
| Var | Controls | Default | Store |
|---|---|---|---|
| `MIMIR_TENANT_ID` | Default/legacy `X-Scope-OrgID` when no tenant org resolves | `system` | ConfigMap |
| `AM_PROVISION_ENABLED` | Enable pushing per-org Alertmanager webhook configs | `False` | ConfigMap |
| `ATLAS_PUBLIC_URL` | Public base URL (carries `ROOT_PATH`); used in AM webhook + OIDC redirect | `""` | ConfigMap |
| `INGEST_API_KEY` | Shared key for the legacy un-orged ingest route | `""` | Secret |

### Sync / correlation / retention
| Var | Controls | Default | Store |
|---|---|---|---|
| `SYNC_INTERVAL_SECONDS` | Rule-sync worker loop interval | `30` | ConfigMap |
| `CLAIM_LOOKBACK_DAYS` | Claim-scan lower bound (partition pruning) | `7` | ConfigMap |
| `ARCHIVE_DIR` | gzip-CSV archive target for dropped partitions; `""` = no archive | `""` | ConfigMap (mounted vol) |

### Notification / delivery
| Var | Controls | Default | Store |
|---|---|---|---|
| `SEND_CONCURRENCY_CAP` | Max per-tenant concurrent sends (RTT pipelining) | `16` | ConfigMap |
| `SEND_RTT_ESTIMATE_SECONDS` | RTT estimate feeding the concurrency calc | `0.15` | ConfigMap |
| `NOTIFY_PENDING_SOFTCAP` | Default per-service pending-queue alarm threshold (alert, never shed) | `50000` | ConfigMap |

### Email / SMTP
| Var | Controls | Default | Store |
|---|---|---|---|
| `SMTP_HOST` | SMTP server | `localhost` | ConfigMap |
| `SMTP_PORT` | SMTP port | `25` | ConfigMap |
| `SMTP_USER` | SMTP username | `""` | ConfigMap |
| `SMTP_PASSWORD` | SMTP password | `""` | Secret |
| `SMTP_FROM` | From address | `atlas@example.com` | ConfigMap |
| `SMTP_STARTTLS` | Use STARTTLS | `False` | ConfigMap |

### OIDC / SSO (all Secret — client credentials)
| Var | Controls | Default | Store |
|---|---|---|---|
| `OIDC_ISSUER` | OIDC issuer URL; `""` disables SSO | `""` | Secret |
| `OIDC_CLIENT_ID` | OIDC client id | `""` | Secret |
| `OIDC_CLIENT_SECRET` | OIDC client secret | `""` | Secret |
| `OIDC_REDIRECT_URI` | OIDC callback (carries `ROOT_PATH`) | `""` | Secret |

### Frontend-facing / CORS
| Var | Controls | Default | Store |
|---|---|---|---|
| `CORS_ORIGINS` | Comma-separated allowed origins (origin-only, no path) | `http://localhost:5173` | ConfigMap |
| `FRONTEND_URL` | Frontend base (OIDC post-login redirect; carries `ROOT_PATH`) | `http://localhost:5173` | ConfigMap |

### LLM analysis
| Var | Controls | Default | Store |
|---|---|---|---|
| `LLM_REQUEST_TIMEOUT_SECONDS` | Per-request timeout for the LLM client | `60.0` | ConfigMap |

> Per-service LLM endpoint/key/model/quota are **not** env vars — they live in the
> `llm_config` table (Fernet-encrypted key), admin-managed.

### Self-observability (metrics / health)
| Var | Controls | Default | Store |
|---|---|---|---|
| `METRICS_PORT` | Port for each worker's `/metrics`+`/healthz`+`/readyz` server | `9100` | ConfigMap |
| `METRICS_DB_CACHE_SECONDS` | TTL for DB-derived gauges on the API `/metrics` scrape | `15.0` | ConfigMap |

---

## 5. Where per-env config lives (both repos)

- **base** = env-agnostic only (`atlas-config` as a `configMapGenerator` with
  shared keys, Deployments, Ingress). **No `images:` block, no patches.**
- **overlay** (`infrastructure/{dev,prd}` in gitops; `deploy/k8s/overlays/{dev,prod}`
  in the app repo) = `resources: [../base, …]` + `images:` (tags) + `patches:`
  (ConfigMap values, replicas, ingress host) at the **top-level kustomization.yaml**.
- Per-env config (observability URLs, `APP_ENV`, `COOKIE_SECURE`, ingress host,
  replicas, image tags) → overlay top-level `kustomization.yaml`. **Never** in a
  base sub-folder — patches there don't reach base resources.

---

## 6. Auto-rollout on config change (configMapGenerator hash)

**Why pods don't pick up ConfigMap changes by default:** the app reads env vars
once, at process start (pydantic). A plain `kubectl`/Flux ConfigMap update mutates
the object but does **not** touch the Deployment's pod template, so the running
pods keep the value they booted with. Result: "I changed the ConfigMap but the
pod still has the old value." A pod restart is required to re-read env.

**The fix — `configMapGenerator`:** kustomize appends a **content-hash suffix** to
the generated ConfigMap's name (`atlas-config-<hash>`) and rewrites every
`envFrom.configMapRef.name` (backend + all workers) to match. Change any key →
new hash → new name → the pod template changes → new ReplicaSet → automatic
rollout. The restart is no longer manual.

**Fits our base(generator)+overlay(JSON6902 patches) structure:** kustomize runs
`patches` **before** the hash transformer, so the overlay's `op: add/replace
/data/...` patches still apply and the suffix reflects the *final merged* content.
No need to convert the overlay patches to generator `behavior: merge`.

**base kustomization.yaml (both repos):**
```yaml
# replaces the plain `- configmap.yaml` resource
configMapGenerator:
  - name: atlas-config
    namespace: atlas
    literals:
      - APP_ENV=prod
      - ROOT_PATH=/alert-hub
      - MIMIR_TENANT_ID=system
      - SYNC_INTERVAL_SECONDS=30
# hash is ENABLED on purpose — do NOT set generatorOptions.disableNameSuffixHash
```
Overlays are unchanged — their ConfigMap patches (and replicas/ingress patches)
keep targeting `kind: ConfigMap, name: atlas-config`.

> **Caveat — Secrets don't auto-roll:** the dev `secretGenerator` sets
> `disableNameSuffixHash: true` (stable name), so changing `atlas-secrets` does
> NOT roll pods. Either drop that option (accept hashed secret names) or
> `kubectl rollout restart` after a secret change. Not changed here since this
> work only touched `atlas-config`.

> **Render-verify the hash:** `kubectl kustomize infrastructure/dev | grep "name: atlas-config"`
> should show a `-<hash>` suffix, and the backend/worker `configMapRef` should
> reference that same suffixed name.
