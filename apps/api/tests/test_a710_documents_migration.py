"""A7.10's migration (``a7d1c3e5f9b2``) on PostgreSQL: up, down, up.

The downgrade refuses while a document is stored.
"""

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
BEFORE = "f1a9c7e3b5d2"
THIS = "a7d1c3e5f9b2"


def test_a710_migration_up_down_up(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, THIS)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('AAPL', 'Apple', true, 'USD', now())"
                ))  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers WHERE value = 'AAPL'"
                )).scalar_one()  # fmt: skip
                doc = conn.execute(text(
                    "INSERT INTO documents (instrument_id, kind, source, title, available_at, "
                    "available_assumed, sha256, content_type, size_bytes, text_chars, created_at) "
                    "VALUES (:i, 'filing', 'file', 't', now(), false, 'abc', 'text', 3, 3, now()) "
                    "RETURNING id"
                ), {"i": iid}).scalar_one()  # fmt: skip
                conn.execute(
                    text("INSERT INTO document_texts (document_id, text) VALUES (:d, 'abc')"),
                    {"d": doc},
                )
            with pytest.raises(Exception, match="ck_documents_kind"), engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO documents (instrument_id, kind, source, title, available_at, "
                    "available_assumed, sha256, content_type, size_bytes, text_chars, created_at) "
                    "VALUES (:i, 'memo', 'file', 't', now(), false, 'abd', 'text', 3, 3, now())"
                ), {"i": iid})  # fmt: skip
            command.upgrade(config, "head")
            command.check(config)
            with pytest.raises(RuntimeError, match="documents are stored"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM documents"))
                left = conn.execute(text("SELECT count(*) FROM document_texts")).scalar_one()
                assert left == 0  # cascade
            command.downgrade(config, BEFORE)
            assert "documents" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "document_texts" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
