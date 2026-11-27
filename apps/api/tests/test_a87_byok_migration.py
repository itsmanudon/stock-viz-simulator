"""A8.7's migration (``e9c5f7a1b3d4``) on PostgreSQL: up, check, down refused, down, up."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "d8b4e6f0a2c3"
THIS = "e9c5f7a1b3d4"


def test_a87_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            command.check(config)
            with engine.begin() as conn:
                uid = conn.execute(text(
                    "INSERT INTO users (email, public_profile, created_at) "
                    "VALUES ('k@stockviz.dev', false, now()) RETURNING id"
                )).scalar_one()  # fmt: skip
                conn.execute(text(
                    "INSERT INTO user_ai_keys (user_id, provider, ciphertext, key_last4, model, "
                    "created_at, updated_at) VALUES (:u, 'openai_compatible', 'x', 'abcd', 'm', "
                    "now(), now())"
                ), {"u": uid})  # fmt: skip
            with pytest.raises(Exception, match="ck_user_ai_keys_provider"), engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO user_ai_keys (user_id, provider, ciphertext, key_last4, model, "
                    "created_at, updated_at) VALUES (:u, 'gemini', 'x', 'abcd', 'm', now(), now())"
                ), {"u": uid})  # fmt: skip
            with pytest.raises(RuntimeError, match="saved AI keys are stored"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM users"))
                assert conn.execute(text("SELECT count(*) FROM user_ai_keys")).scalar_one() == 0
            command.downgrade(config, BEFORE)
            assert "user_ai_keys" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "user_ai_keys" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
