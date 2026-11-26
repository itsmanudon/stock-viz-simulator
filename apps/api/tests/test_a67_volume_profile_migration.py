"""A6.7's migration (``d4a7f9b1c3e5``) on PostgreSQL: up, down, up.

``ck_drawings_kind`` takes ``volume_profile``; the downgrade refuses while one
is stored, and after it the kind is refused again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "d4a8f6c2b1e9"
THIS = "d4a7f9b1c3e5"

INSERT = text(
    "INSERT INTO drawings (user_id, instrument_id, kind, points, style, label, locked, "
    "created_at, updated_at) VALUES (:u, :i, :k, :p, '{}', null, false, now(), now())"
)
POINTS = '[{"ts": "2025-11-24", "price": null}, {"ts": "2025-11-25", "price": null}]'


def test_a67_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('AAPL', 'Apple', true, 'USD', now())"
                ))  # fmt: skip
                uid = conn.execute(text(
                    "INSERT INTO users (email, public_profile, created_at) "
                    "VALUES ('a@x.dev', false, now()) RETURNING id"
                )).scalar_one()  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers WHERE value = 'AAPL'"
                )).scalar_one()  # fmt: skip
            row = {"u": uid, "i": iid, "k": "volume_profile", "p": POINTS}
            with pytest.raises(Exception, match="ck_drawings_kind"), engine.begin() as conn:
                conn.execute(INSERT, row)

            command.upgrade(config, THIS)
            with engine.begin() as conn:
                conn.execute(INSERT, row)
                conn.execute(INSERT, {**row, "k": "avwap", "p": '[{"ts": "2025-11-24"}]'})
            # The models match the head schema.
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, THIS)

            with pytest.raises(RuntimeError, match="volume_profile drawings are stored"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM drawings WHERE kind = 'volume_profile'"))
            command.downgrade(config, BEFORE)
            with pytest.raises(Exception, match="ck_drawings_kind"), engine.begin() as conn:
                conn.execute(INSERT, row)
            with engine.begin() as conn:
                kinds = conn.execute(text("SELECT kind FROM drawings")).scalars().all()
                assert kinds == ["avwap"]

            command.upgrade(config, THIS)
            with engine.begin() as conn:
                conn.execute(INSERT, row)
        finally:
            engine.dispose()
            get_settings.cache_clear()
