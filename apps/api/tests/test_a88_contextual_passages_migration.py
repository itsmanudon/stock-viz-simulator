"""A8.8's migration (``f2b4d6e8a0c1``): context columns, the index on context and text.

Up to head, ``alembic check``, a real stemmed keyword match on a word only in
the context (through the GIN index expression), the downgrade refused while a
context is stored, then down and up again once it is cleared.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from stockviz.models import DocumentChunk
from stockviz.services.documents import context, retrieve
from stockviz.services.documents.extract import Extracted
from stockviz.services.documents.store import NewDocument, add_document
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "e9c5f7a1b3d4"
THIS = "f2b4d6e8a0c1"


def test_a88_migration_and_context_search(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            command.check(config)
            index_sql = text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_tsv'"
            )
            with engine.begin() as conn:
                assert "COALESCE(context, ''::text)" in conn.execute(index_sql).scalar_one()
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('AAPL', 'Apple Inc.', true, 'USD', now())"
                ))  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers WHERE value = 'AAPL'"
                )).scalar_one()  # fmt: skip
            body = "Net sales increased 8% during the quarter."
            when = datetime(2027, 1, 1)
            with Session(engine) as session:
                add_document(
                    session,
                    NewDocument(instrument_id=iid, kind="filing", source="edgar", title="10-Q",
                                available_at=datetime(2026, 8, 1), accession="0000320193-26-1"),
                    body.encode(),
                    Extracted("text", body),
                )  # fmt: skip
                session.commit()
                assert retrieve.retrieve(session, "smartphones", as_of=when).passages == []
                chunk = session.exec(select(DocumentChunk)).one()
                context.set_context(chunk, "Apple 10-Q: revenue from smartphones (iPhone).", "m")
                session.add(chunk)
                session.commit()
                found = retrieve.retrieve(session, "smartphone revenue", as_of=when)  # stemmed
                assert [p.chunk_id for p in found.passages] == [chunk.id]
            with pytest.raises(RuntimeError, match="1 passage"):
                command.downgrade(config, BEFORE)
            with engine.begin() as conn:
                conn.execute(text("UPDATE document_chunks SET context = NULL"))
            command.downgrade(config, BEFORE)
            cols = {c["name"] for c in inspect(engine).get_columns("document_chunks")}
            assert "context" not in cols and "context_model" not in cols
            with engine.begin() as conn:
                assert "COALESCE" not in conn.execute(index_sql).scalar_one()
            command.upgrade(config, THIS)
            cols = {c["name"] for c in inspect(engine).get_columns("document_chunks")}
            assert {"context", "context_model"} <= cols
        finally:
            get_settings.cache_clear()
