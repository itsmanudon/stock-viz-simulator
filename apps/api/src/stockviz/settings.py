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


@lru_cache
def get_settings() -> Settings:
    return Settings()
