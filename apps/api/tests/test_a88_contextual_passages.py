"""A8.8 (M11.1): a model-written context line per passage, searched and embedded with it."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import DocumentChunk
from stockviz.services.ai import copilot
from stockviz.services.ai.provider import AiProviderError, Message
from stockviz.services.documents import context, retrieve
from stockviz.services.documents.extract import Extracted
from stockviz.services.documents.index import embed_input, index_documents
from stockviz.services.documents.store import NewDocument, add_document
from stockviz.services.instruments import instrument_ids
from tests.symbols import seed_symbols
from tests.test_a84_hybrid_search import FakeEmbedder

BODY = (
    "PART I\nItem 2. Management's Discussion and Analysis\n\n"
    "Net sales increased 8% to $94,930 million during the quarter."
)
AT = datetime(2026, 8, 1, 12)


class FakeModel:
    name = "fake"
    model = "fake-ctx"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        self.prompts.append(messages[-1].content)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def filing(session: Session) -> int:
    seed_symbols(session, "AAPL", currency="USD")
    iid = instrument_ids(session, ["AAPL"])["AAPL"]
    doc, _ = add_document(
        session,
        NewDocument(instrument_id=iid, kind="filing", source="edgar", title="10-Q for 2026-06-27",
                    available_at=AT, form_type="10-Q", event_date=date(2026, 6, 27),
                    accession="0000320193-26-000070"),
        BODY.encode(),
        Extracted("text", BODY),
    )  # fmt: skip
    session.commit()
    assert doc.id is not None
    return doc.id


def _chunk(session: Session, doc_id: int) -> DocumentChunk:
    return session.exec(select(DocumentChunk).where(col(DocumentChunk.document_id) == doc_id)).one()


def test_section_of_finds_the_nearest_heading() -> None:
    assert context.section_of(BODY, len(BODY)) == "Item 2. Management's Discussion and Analysis"
    assert context.section_of(BODY, 3) == "unknown"


def test_generate_writes_a_context_and_clears_the_vector(session: Session, filing: int) -> None:
    chunk = _chunk(session, filing)
    chunk.embedding, chunk.embed_model = [1.0, 2.0], "old"
    session.add(chunk)
    session.commit()
    model = FakeModel(
        ['  "Apple Inc. 10-Q, quarter ended June 27, 2026, MD&A: net sales growth."  ']
    )
    report = context.generate(session, model, {}, limit=None)
    assert (report.written, report.failed, report.waiting) == (1, 0, 0)
    prompt = model.prompts[0]
    assert "10-Q for the period ending 2026-06-27" in prompt
    assert "Section (nearest heading before the passage): " in prompt
    assert "<passage>\n" + chunk.text in prompt
    session.refresh(chunk)
    assert chunk.context == "Apple Inc. 10-Q, quarter ended June 27, 2026, MD&A: net sales growth."
    assert (
        chunk.context_model == "fake-ctx" and chunk.embedding is None and chunk.embed_model is None
    )


def test_failed_and_empty_replies_are_skipped(session: Session, filing: int) -> None:
    model = FakeModel([AiProviderError("Ollama is not reachable (ConnectError)")])
    report = context.generate(session, model, {})
    assert (report.written, report.failed, report.waiting) == (0, 1, 1)
    assert report.notes == ["Ollama is not reachable (ConnectError)"]
    report = context.generate(session, FakeModel(["ok"]), {})
    assert (report.written, report.failed) == (0, 1)
    assert _chunk(session, filing).context is None


def test_context_is_searched_embedded_and_shown_to_the_model(session: Session, filing: int) -> None:
    chunk = _chunk(session, filing)
    when = datetime(2027, 1, 1)
    assert retrieve.retrieve(session, "iphone maker revenue", as_of=when).passages == []
    context.set_context(chunk, "Apple, the iPhone maker: quarterly revenue (net sales).", "m")
    session.add(chunk)
    session.commit()
    found = retrieve.retrieve(session, "iphone maker", as_of=when)
    assert [p.chunk_id for p in found.passages] == [chunk.id]
    assert found.passages[0].context == "Apple, the iPhone maker: quarterly revenue (net sales)."
    assert embed_input(chunk).startswith("Apple, the iPhone maker") and BODY[-20:] in embed_input(
        chunk
    )
    emb = FakeEmbedder()
    assert index_documents(session, embedder=emb).chunks_embedded == 1
    user = copilot.build_messages(
        "Revenue?", found.passages, {found.passages[0].document.instrument_id: "AAPL"}
    )[1]
    assert "(About this passage: Apple, the iPhone maker" in user.content
    assert "$94,930 million" in user.content


def test_export_and_import_move_contexts_by_accession_and_position(
    session: Session, filing: int, tmp_path
) -> None:
    chunk = _chunk(session, filing)
    rows = [
        {"accession": "0000320193-26-000070", "position": chunk.position,
         "context": "Apple Inc. 10-Q, quarter ended June 27, 2026: net sales.", "model": "claude-haiku-5-5"},
        {"accession": "0000320193-26-000070", "position": 99, "context": "no such passage here", "model": "m"},
        {"accession": "nope", "position": 0, "context": "unknown filing accession", "model": "m"},
    ]  # fmt: skip
    assert context.import_rows(session, rows) == (1, 2)
    session.refresh(chunk)
    assert chunk.context_model == "claude-haiku-5-5" and chunk.embedding is None
    assert list(context.export(session)) == [rows[0]]


def test_cli_imports_and_exports_on_a_local_database(
    session: Session, filing: int, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "engine", session.get_bind())
    chunk = _chunk(session, filing)
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps({"accession": "0000320193-26-000070", "position": chunk.position,
                               "context": "Apple Inc. 10-Q: net sales for the quarter.", "model": "m"}) + "\n")  # fmt: skip
    assert cli.main(["docs-context", "--import", str(src)]) == 0
    assert "imported 1 context(s); 0 row(s) matched no passage" in capsys.readouterr().out
    out = tmp_path / "out.jsonl"
    assert cli.main(["docs-context", "--export", str(out)]) == 0
    assert json.loads(out.read_text())["context"] == "Apple Inc. 10-Q: net sales for the quarter."


def test_cli_needs_a_key_for_claude(session: Session, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", session.get_bind())
    monkeypatch.setattr(cli, "_local_anthropic_key", lambda: "")
    assert cli.main(["docs-context", "--claude", "claude-haiku-5-5"]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
