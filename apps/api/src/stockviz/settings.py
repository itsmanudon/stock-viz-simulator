import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    @field_validator("database_url")
    @classmethod
    def _force_psycopg3_driver(cls, raw: str) -> str:
        # Render/Heroku hand us `postgres://...` or `postgresql://...` with no
        # driver hint, which makes SQLAlchemy default to psycopg2 (not installed).
        # We depend on psycopg3, so rewrite to `postgresql+psycopg://...`.
        if raw.startswith("postgres://"):
            return "postgresql+psycopg://" + raw[len("postgres://") :]
        if raw.startswith("postgresql://"):
            return "postgresql+psycopg://" + raw[len("postgresql://") :]
        return raw

    # NoDecode disables pydantic-settings' default JSON parsing for this field,
    # so the env value reaches the validator below as a raw string. Accepts:
    #   - a single URL:        https://app.vercel.app
    #   - comma-separated:     https://a.com,https://b.com
    #   - JSON array:          ["https://app.vercel.app"]
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, raw: object) -> object:
        if not isinstance(raw, str):
            return raw
        s = raw.strip()
        if not s:
            return []
        if s.startswith("["):
            return json.loads(s)
        return [item.strip() for item in s.split(",") if item.strip()]

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

    # Sentry — leave empty to disable (dev/CI default).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1


@lru_cache
def get_settings() -> Settings:
    return Settings()
