from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "dev"
    SECRET_KEY: str = "dev-secret-key-change-me"
    FERNET_KEY: str = ""

    # Subpath deploy: when atlas is served under a path prefix (e.g. /alert-hub)
    # behind an ingress that STRIPS the prefix, root_path tells FastAPI to
    # generate docs/openapi/cookie URLs with it. "" = served at root. Must match
    # the frontend VITE_BASE_PATH (without trailing slash).
    ROOT_PATH: str = ""

    DATABASE_URL: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
    REDIS_URL: str = "redis://localhost:6379/0"

    # The single Mimir org (X-Scope-OrgID), set on every observability-stack
    # client by integrations/base.py::make_client.
    MIMIR_TENANT_ID: str = "system"
    ATLAS_PUBLIC_URL: str = ""
    # Phase 3: partition/retention maintenance
    ARCHIVE_DIR: str = ""  # gzip-CSV archive target (mounted volume); empty = no archive
    CLAIM_LOOKBACK_DAYS: int = 7  # claim-scan lower bound -> partition pruning
    # Phase 4: notification send pipelining. concurrency = ceil(rate*RTT)+4
    # capped at SEND_CONCURRENCY_CAP; the per-tenant TokenBucket still enforces
    # the sustained rate — concurrency just fills the RTT pipe to saturate it.
    SEND_CONCURRENCY_CAP: int = 16
    SEND_RTT_ESTIMATE_SECONDS: float = 0.15
    # Phase 5: observability. Workers expose /metrics+/healthz+/readyz on
    # METRICS_PORT. NOTIFY_PENDING_SOFTCAP is the per-service pending-queue
    # alarm threshold (admin-adjustable via notify_config; alert, never shed).
    METRICS_PORT: int = 9100
    NOTIFY_PENDING_SOFTCAP: int = 50000
    # Send-pipeline guards (per-group channels are config; these are global infra
    # safety). Rate is per group-channel bot bucket; quotas/soft-cap are global.
    NOTIFY_RATE_PER_SECOND: int = 25
    NOTIFY_QUOTA_GROUP_PER_HOUR: int = 30
    NOTIFY_QUOTA_GLOBAL_PER_DAY: int = 500
    LLM_REQUEST_TIMEOUT_SECONDS: float = 60.0
    METRICS_DB_CACHE_SECONDS: float = 15.0
    MIMIR_RULER_URL: str = "http://mimir:8080/prometheus/config/v1/rules"
    MIMIR_ALERTMANAGER_URL: str = "http://mimir-alertmanager:8080"
    MIMIR_QUERY_URL: str = "http://mimir:8080/prometheus"
    LOKI_URL: str = "http://loki:3100"
    TEMPO_URL: str = "http://tempo:3200"
    GRAFANA_URL: str = "http://grafana:3000"

    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = ""

    CORS_ORIGINS: str = "http://localhost:5173"
    FRONTEND_URL: str = "http://localhost:5173"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Refresh/OIDC cookie flags. A `secure` cookie is DROPPED by the browser
    # over plain HTTP, so an HTTP-served env (dev) must set COOKIE_SECURE=false
    # or the refresh cookie is never stored and the session dies at the access
    # TTL. Default true = safe for HTTPS (prod). samesite=strict is fine
    # same-origin; relax to "lax"/"none" only if a cross-context flow breaks.
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "strict"

    SYNC_INTERVAL_SECONDS: int = 30
    MIMIR_SYNC_INTERVAL_SECONDS: int = 60  # ruler-rules + AM-silences read-cache refresh
    INGEST_API_KEY: str = ""
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 25
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "atlas@example.com"
    SMTP_STARTTLS: bool = False
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
