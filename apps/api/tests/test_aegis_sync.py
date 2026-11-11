"""The Aegis read sync, end to end against recorded responses."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisEvent,
    AegisMapping,
    AegisSyncRun,
    AegisSyncState,
)
from stockviz.services.aegis.client import AegisClient, AegisError
from stockviz.services.aegis.read import documents_for_ticker
from stockviz.services.aegis.sync import run_sync

FIXTURES = Path(__file__).parent / "fixtures" / "aegis"
NOW = datetime(2026, 11, 11, 22, 0)


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


PAGE_1 = recorded("feed-page-1.json")
PAGE_2 = recorded("feed-page-2.json")
DOC_A = PAGE_1["data"][0]["document"]["document_id"]  # Apple, withdrawn on page 2
DOC_B = PAGE_1["data"][1]["document"]["document_id"]  # Reliance, re-analysed on page 2


class FakeAegis:
    """Serves the recorded pages by cursor, like the real feed."""

    def __init__(self, *, fail_on_page_2: bool = False, mappings: bool = True) -> None:
        self.feed_cursors: list[str | None] = []
        self.fail_on_page_2 = fail_on_page_2
        self.mappings = mappings

    def __call__(self, request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        if request.url.path == "/api/v1/assets/mappings":
            if not self.mappings:
                return httpx.Response(
                    200, json={"data": [], "pagination": {"has_more": False}, "meta": {}}
                )
            name = "mappings-page-2.json" if cursor else "mappings-page-1.json"
            return httpx.Response(200, json=recorded(name))
        self.feed_cursors.append(cursor)
        if cursor is None:
            return httpx.Response(200, json=PAGE_1)
        if cursor == PAGE_1["resume_cursor"]:
            if self.fail_on_page_2:
                return httpx.Response(
                    403, json={"error": {"code": "FORBIDDEN", "message": "Missing scope"}}
                )
            return httpx.Response(200, json=PAGE_2)
        return httpx.Response(200, json=recorded("feed-empty.json"))


def client_for(fake: FakeAegis) -> AegisClient:
    return AegisClient(
        "https://aegis.example.test",
        token=lambda: "t",
        http=httpx.Client(transport=httpx.MockTransport(fake)),
        sleep=lambda _s: None,
    )


def test_first_page_lands_with_model_identity_and_raw_labels(engine) -> None:
    result = run_sync(engine, client_for(FakeAegis()), max_pages=1, now=lambda: NOW)
    assert (result.pages, result.upserted, result.withdrawn, result.mappings) == (1, 2, 0, 4)

    with Session(engine) as session:
        doc = session.get(AegisDocument, DOC_A)
        assert doc is not None
        assert doc.title == "Apple widens supplier review"
        # GDELT-style: no publisher time, but available_at is always there (AG-12).
        assert doc.published_at is None
        assert doc.available_at == datetime(2026, 11, 10, 15, 43, 19, 856450)
        assert doc.manifest_hash is not None

        sentiment = session.exec(
            select(AegisAnalysis).where(
                AegisAnalysis.document_id == DOC_A, AegisAnalysis.analysis_type == "sentiment"
            )
        ).one()
        # Stored as sent, with the model that produced it (AG-4).
        assert sentiment.label == "mixed"
        assert sentiment.score == pytest.approx(0.04)
        assert (sentiment.provider, sentiment.model_name, sentiment.model_version) == (
            "local-baseline",
            "lexicon-sentiment",
            "1",
        )
        assert {a.analysis_type for a in session.exec(select(AegisAnalysis)).all()} == {
            "topic",
            "sentiment",
            "entity_resolution",
        }
        assert len(session.exec(select(AegisDocumentEntity)).all()) == 2
        assert len(session.exec(select(AegisEvent)).all()) >= 1
        state = session.get(AegisSyncState, 1)
        assert state is not None and state.cursor == PAGE_1["resume_cursor"]


def test_full_run_applies_the_tombstone_and_the_new_analysis(engine) -> None:
    fake = FakeAegis()
    result = run_sync(engine, client_for(fake), now=lambda: NOW)
    assert (result.pages, result.upserted, result.withdrawn) == (2, 3, 1)
    assert fake.feed_cursors == [None, PAGE_1["resume_cursor"]]

    with Session(engine) as session:
        # The withdrawn document and everything under it are gone (AG-11).
        assert session.get(AegisDocument, DOC_A) is None
        for model in (AegisAnalysis, AegisDocumentEntity, AegisEvent):
            assert session.exec(select(model).where(model.document_id == DOC_A)).all() == []

        # The re-analysed document holds only its latest signed run.
        sentiments = session.exec(
            select(AegisAnalysis).where(
                AegisAnalysis.document_id == DOC_B, AegisAnalysis.analysis_type == "sentiment"
            )
        ).all()
        assert [(s.analysis_id, s.label) for s in sentiments] == [
            ("ana_00000000-0000-5000-8000-000000000002", "negative")
        ]
        assert session.exec(select(AegisEvent).where(AegisEvent.document_id == DOC_B)).all() == []
        doc = session.get(AegisDocument, DOC_B)
        assert doc is not None and doc.manifest_hash == "2" * 64

        run = session.exec(select(AegisSyncRun)).one()
        assert run.status == "succeeded"
        assert (run.pages, run.documents_upserted, run.documents_withdrawn) == (2, 3, 1)
        assert run.finished_at == NOW


def test_a_second_run_resumes_from_the_cursor_and_changes_nothing(engine) -> None:
    run_sync(engine, client_for(FakeAegis()), now=lambda: NOW)
    with Session(engine) as session:
        before = len(session.exec(select(AegisAnalysis)).all())

    fake = FakeAegis()
    result = run_sync(engine, client_for(fake), now=lambda: NOW)

    assert fake.feed_cursors == [PAGE_2["resume_cursor"]]
    assert (result.pages, result.upserted, result.withdrawn) == (1, 0, 0)
    with Session(engine) as session:
        assert len(session.exec(select(AegisAnalysis)).all()) == before
        assert len(session.exec(select(AegisSyncRun)).all()) == 2


def test_a_failure_part_way_keeps_the_committed_page_and_records_the_run(engine) -> None:
    with pytest.raises(AegisError):
        run_sync(engine, client_for(FakeAegis(fail_on_page_2=True)), now=lambda: NOW)

    with Session(engine) as session:
        run = session.exec(select(AegisSyncRun)).one()
        assert run.status == "failed"
        assert run.error is not None and "FORBIDDEN" in run.error
        assert run.pages == 1
        # Page 1 and its cursor were committed, so the next run starts at page 2.
        assert session.get(AegisDocument, DOC_A) is not None
        state = session.get(AegisSyncState, 1)
        assert state is not None and state.cursor == PAGE_1["resume_cursor"]

    fake = FakeAegis()
    run_sync(engine, client_for(fake), now=lambda: NOW)
    assert fake.feed_cursors[0] == PAGE_1["resume_cursor"]


def test_documents_join_to_stockviz_tickers_through_the_mapping_list(engine) -> None:
    run_sync(engine, client_for(FakeAegis()), max_pages=1, now=lambda: NOW)
    with Session(engine) as session:
        assert [d.document_id for d in documents_for_ticker(session, "aapl")] == [DOC_A]
        assert [d.document_id for d in documents_for_ticker(session, "RELIANCE.NS")] == [DOC_B]
        assert documents_for_ticker(session, "MSFT") == []
        # Point in time on available_at: before Aegis had it, StockViz shows nothing.
        assert documents_for_ticker(session, "AAPL", as_of=datetime(2026, 11, 10, 15, 0)) == []


def test_a_mapping_added_later_links_documents_already_held(engine) -> None:
    """The join runs at read time (AG-2): no re-delivery needed."""
    run_sync(engine, client_for(FakeAegis(mappings=False)), max_pages=1, now=lambda: NOW)
    with Session(engine) as session:
        assert documents_for_ticker(session, "AAPL") == []

    # Next night the mapping list has the listing; the feed has nothing new.
    with Session(engine) as session:
        state = session.get(AegisSyncState, 1)
        assert state is not None
        state.cursor = PAGE_2["resume_cursor"]
        session.add(state)
        session.commit()
    run_sync(engine, client_for(FakeAegis()), now=lambda: NOW)
    with Session(engine) as session:
        assert [d.document_id for d in documents_for_ticker(session, "AAPL")] == [DOC_A]
        assert len(session.exec(select(AegisMapping)).all()) == 4


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_skips_with_exit_2_when_not_configured(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(aegis_configured=False))
    assert cli.main(["aegis-sync"]) == 2
    assert "Skipping" in capsys.readouterr().err


def test_cli_runs_the_sync_with_a_minted_token(engine, monkeypatch, capsys) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    pem = (
        Ed25519PrivateKey.generate()
        .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        .decode()
    )
    settings = SimpleNamespace(
        aegis_configured=True,
        aegis_signing_key=pem,
        aegis_key_id="stockviz-2026",
        aegis_issuer="https://aegis.example.test",
        aegis_audience="aegisnews",
        aegis_client_id="stockviz-sync",
        aegis_base_url="https://aegis.example.test",
        aegis_timeout_seconds=5.0,
        aegis_page_limit=100,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "engine", engine)
    fake = FakeAegis()
    auth: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        auth.append(request.headers["authorization"])
        return fake(request)

    real_client = httpx.Client
    monkeypatch.setattr(
        "stockviz.services.aegis.client.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw),
    )

    assert cli.main(["aegis-sync"]) == 0
    out = capsys.readouterr().out
    assert "2 page(s), 3 document(s) upserted, 1 withdrawn, 4 mapping(s)" in out
    assert all(value.startswith("Bearer ey") for value in auth)
