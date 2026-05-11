from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "stockviz-api"
    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz"

    cors_origins: list[str] = ["http://localhost:3000"]

    nextauth_jwt_secret: str = "dev-secret-change-me"

    alpha_vantage_key: str = ""
    newsdata_key: str = ""

    # APScheduler is off by default so tests, migrations, and ad-hoc CLI runs
    # don't accidentally trigger external API calls. The deployed server flips
    # this on via env.
    enable_scheduler: bool = False

    # Shared secret used by the Next.js server-side API client to identify
    # itself when calling authenticated /v1 endpoints (paper-trading writes).
    # Phase 7 will swap this for real NextAuth JWT verification; for now the
    # token + ``X-User-Id`` header pair is a server-to-server trust bridge.
    internal_api_token: str = "dev-internal-token-change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
