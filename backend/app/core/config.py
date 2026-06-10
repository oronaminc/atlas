from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "dev"
    SECRET_KEY: str = "dev-secret-key-change-me"
    FERNET_KEY: str = ""

    DATABASE_URL: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Multi-tenancy: always sent as X-Scope-OrgID on every Mimir/Loki/Tempo call.
    MIMIR_TENANT_ID: str = "system"
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
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
