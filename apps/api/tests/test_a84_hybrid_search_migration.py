"""A8.4's migration (``d8b4e6f0a2c3``) and full-text ranking on PostgreSQL.

Up to head, ``alembic check``, a real ``websearch_to_tsquery`` ranking (with
stemming, which the SQLite stand-in lacks) and ``real[]`` vectors, then down
and up again.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session

from stockviz.services.documents import retrieve
from stockviz.services.documents.extract import Extracted
from stockviz.services.documents.index import index_documents
from stockviz.services.documents.store import NewDocument, add_document
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_alembic_engine
from tests.test_a84_hybrid_search import FakeEmbedder
from tests.test_intraday_migration import _keep_logging  # noqa: F401

pytestmark = pytest.mark.skipif(
    postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL"
)

API_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "c8a3d5f7e9b1"
THIS = "d8b4e6f0a2c3"


def test_a84_migration_and_full_text_ranking(monkeypatch) -> None:
    with scratch_alembic_engine() as engine:
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(API_ROOT / "migrations"))
            command.upgrade(config, "head")
            command.check(config)
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO symbols (ticker, name, is_active, currency, created_at) "
                    "VALUES ('TCS.NS', 'TCS', true, 'INR', now())"
                ))  # fmt: skip
                iid = conn.execute(text(
                    "SELECT instrument_id FROM instrument_identifiers WHERE value = 'TCS.NS'"
                )).scalar_one()  # fmt: skip
            with Session(engine) as session:
                for title, body in (
                    ("Q2", "Borrowings were repaid in full. Sales grew nine percent."),
                    ("Q3", "Headcount fell; attrition eased."),
                ):
                    add_document(
                        session,
                        NewDocument(instrument_id=iid, kind="filing", source="file", title=title,
                                    available_at=datetime(2026, 10, 9)),
                        body.encode(),
                        Extracted("text", body),
                    )  # fmt: skip
                session.commit()
                when = datetime(2027, 1, 1)
                got = retrieve.retrieve(session, "borrowing repaid", as_of=when)
                assert [p.document.title for p in got.passages] == ["Q2"]  # stemmed
                assert retrieve.retrieve(session, '"sales grew" -headcount', as_of=when).passages
                assert (
                    retrieve.retrieve(session, "borrowing", as_of=datetime(2026, 1, 1)).passages
                    == []
                )
                index_documents(session, embedder=FakeEmbedder())
                hybrid = retrieve.retrieve(session, "leverage", as_of=when, embedder=FakeEmbedder())
                assert hybrid.mode == "hybrid" and hybrid.passages[0].document.title == "Q2"
                assert hybrid.passages[0].keyword_rank is None
            indexes = {i["name"] for i in inspect(engine).get_indexes("document_chunks")}
            assert "ix_document_chunks_tsv" in indexes
            command.downgrade(config, BEFORE)
            assert "document_chunks" not in inspect(engine).get_table_names()
            command.upgrade(config, THIS)
            assert "document_chunks" in inspect(engine).get_table_names()
        finally:
            get_settings.cache_clear()
