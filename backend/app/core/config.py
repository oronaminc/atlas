from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "dev"
    SECRET_KEY: str = "dev-secret-key-change-me"
    FERNET_KEY: str = ""

    DATABASE_URL: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Default/legacy Mimir org (X-Scope-OrgID) used when no tenant org is
    # resolved. Per-tenant orgs come from mimir_org_map (core/tenancy.py).
    MIMIR_TENANT_ID: str = "system"
    # AM webhook provisioning: push per-org Alertmanager configs pointing
    # back at {ATLAS_PUBLIC_URL}/api/v1/ingest/alertmanager/{org}.
    AM_PROVISION_ENABLED: bool = False
    ATLAS_PUBLIC_URL: str = ""
    # Phase 3: partition/retention maintenance
    ARCHIVE_DIR: str = ""  # gzip-CSV archive target (mounted volume); empty = no archive
    CLAIM_LOOKBACK_DAYS: int = 7  # claim-scan lower bound -> partition pruning
    # Phase 4: notification send pipelining. concurrency = ceil(rate*RTT)+4
    # capped at SEND_CONCURRENCY_CAP; the per-tenant TokenBucket still enforces
    # the sustained rate — concurrency just fills the RTT pipe to saturate it.
    SEND_CONCURRENCY_CAP: int = 16
    SEND_RTT_ESTIMATE_SECONDS: float = 0.15
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

    SYNC_INTERVAL_SECONDS: int = 30
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
