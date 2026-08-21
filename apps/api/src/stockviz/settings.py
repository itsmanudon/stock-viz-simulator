from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})

_DEV_SECRET_DEFAULTS = {
    "internal_api_token": "dev-internal-token-change-me",
    "nextauth_jwt_secret": "dev-secret-change-me",
}
"""Secrets whose committed dev defaults must never reach production."""


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

    # Legacy: no longer read by the auth bridge, kept so deployments that
    # still set it don't trip config drift.
    nextauth_jwt_secret: str = "dev-secret-change-me"

    alpha_vantage_key: str = ""
    newsdata_key: str = ""
    anthropic_api_key: str = ""

    # APScheduler is off by default so tests, migrations, and ad-hoc CLI runs
    # don't accidentally trigger external API calls. The deployed server flips
    # this on via env.
    enable_scheduler: bool = False

    # Shared HS256 secret for the web -> api bridge. The Next.js server signs
    # a 60 s JWT with it (apps/web/lib/api/server.ts) and auth.require_user_id
    # verifies it. Must be identical on both sides.
    internal_api_token: str = "dev-internal-token-change-me"

    # Sentry — leave empty to disable (dev/CI default).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    @model_validator(mode="after")
    def _reject_dev_secrets_in_production(self) -> Settings:
        """Refuse to boot in production while a secret is still its dev default.

        ``internal_api_token`` signs the web -> api bridge JWT, and
        ``auth.require_user_id`` trusts the ``sub`` claim as the user id. The
        dev default is published in this repository, so if it ever reached
        production anyone could mint a token for any user and read or modify
        their portfolio.

        ``render.yaml`` marks these ``sync: false``, meaning they have to be
        set by hand after the first deploy — exactly the kind of step that gets
        missed. Failing loudly at startup beats failing open.
        """

        if self.environment.strip().lower() not in _PRODUCTION_ENVIRONMENTS:
            return self

        offenders = [
            name
            for name, default in _DEV_SECRET_DEFAULTS.items()
            if getattr(self, name, None) == default
        ]
        if offenders:
            raise ValueError(
                "Refusing to start in production with development secrets still in place: "
                + ", ".join(sorted(name.upper() for name in offenders))
                + ". Set them to real values (e.g. `openssl rand -base64 32`)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
