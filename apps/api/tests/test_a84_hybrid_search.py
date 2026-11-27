"""A8.4 (M11.1): chunks, embeddings and hybrid passage search, point-in-time."""

from __future__ import annotations

import itertools
import json
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import DocumentChunk
from stockviz.services.ai.embed import OllamaEmbedder
from stockviz.services.ai.provider import AiProviderError
from stockviz.services.documents import retrieve
from stockviz.services.documents.chunks import SIZE, spans
from stockviz.services.documents.extract import Extracted
from stockviz.services.documents.index import index_documents
from stockviz.services.documents.store import NewDocument, add_document
from stockviz.services.instruments import instrument_ids
from tests.symbols import seed_symbols

# Concepts the fake model knows: synonyms share a dimension.
CONCEPTS = [
    {"revenue", "sales", "topline"},
    {"margin", "margins", "profitability"},
    {"debt", "borrowings", "leverage"},
    {"hiring", "headcount", "attrition"},
]


class FakeEmbedder:
    model = "fake-embed"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail = fail

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        self.calls.append((task, len(texts)))
        if self.fail:
            raise AiProviderError("Ollama is not reachable (ConnectError)")
        out = []
        for t in texts:
            words = {w.strip(".,").lower() for w in t.split()}
            out.append([float(len(words & c)) for c in CONCEPTS] + [0.01])
        return out


def _doc(session: Session, ticker: str, title: str, text: str, at: datetime) -> int:
    iid = instrument_ids(session, [ticker])[ticker]
    doc, _ = add_document(
        session,
        NewDocument(instrument_id=iid, kind="concall_transcript", source="file", title=title,
                    available_at=at),
        f"{title}{text}".encode(),
        Extracted("text", text),
    )  # fmt: skip
    session.commit()
    assert doc.id is not None
    return doc.id


@pytest.fixture
def corpus(session: Session) -> dict[str, int]:
    seed_symbols(session, "TCS.NS", "INFY.NS", currency="INR")
    return {
        "q2": _doc(session, "TCS.NS", "TCS Q2",
                   "Sales grew nine percent in the quarter.\n\nBorrowings were repaid in full.",
                   datetime(2026, 10, 9, 12)),
        "q3": _doc(session, "TCS.NS", "TCS Q3", "Headcount fell by two thousand.",
                   datetime(2027, 1, 9, 12)),
        "infy": _doc(session, "INFY.NS", "INFY Q2", "Operating margin widened to 21 percent.",
                     datetime(2026, 10, 15, 12)),
    }  # fmt: skip


def test_spans_cover_the_text_with_overlap_and_clean_cuts() -> None:
    para = ("The order book grew strongly this year. " * 20).strip()
    text = "\n\n".join([para] * 5)
    got = spans(text)
    assert len(got) > 3 and got[0].start == 0 and got[-1].end == len(text)
    for a, b in itertools.pairwise(got):
        assert b.start < a.end  # overlap
        assert a.end - a.start <= SIZE
        assert text[b.start - 1] in " \n"  # never starts mid-word
    assert spans("") == [] and spans("   \n ") == []
    assert spans("short") == [type(got[0])(0, 5)]


def test_storing_a_document_chunks_it(session: Session, corpus: dict[str, int]) -> None:
    rows = session.exec(
        select(DocumentChunk).where(col(DocumentChunk.document_id) == corpus["q2"])
    ).all()
    assert len(rows) == 1 and rows[0].embedding is None and "Borrowings" in rows[0].text


def test_keyword_only_without_a_model_and_point_in_time(
    session: Session, corpus: dict[str, int]
) -> None:
    got = retrieve.retrieve(session, "headcount", as_of=datetime(2026, 12, 1))
    assert got.mode == "keyword" and got.passages == []  # Q3 not public yet
    assert "no embedding model" in got.notes[0]
    later = retrieve.retrieve(session, "headcount", as_of=datetime(2027, 2, 1))
    assert [p.document.id for p in later.passages] == [corpus["q3"]]
    assert later.passages[0].keyword_rank == 1 and later.passages[0].vector_rank is None


def test_hybrid_finds_synonyms_keyword_misses(session: Session, corpus: dict[str, int]) -> None:
    fake = FakeEmbedder()
    report = index_documents(session, embedder=fake)
    assert report.chunks_embedded == 3 and report.chunks_waiting == 0
    assert fake.calls == [("document", 3)]
    again = index_documents(session, embedder=fake)
    assert again.chunks_embedded == 0  # nothing re-embedded

    when = datetime(2027, 2, 1)
    assert retrieve.retrieve(session, "topline", as_of=when).passages == []
    got = retrieve.retrieve(session, "topline", as_of=when, embedder=fake)
    assert got.mode == "hybrid" and got.passages[0].document.id == corpus["q2"]
    top = got.passages[0]
    assert top.keyword_rank is None and top.vector_rank == 1 and top.similarity
    assert top.similarity > 0.7  # the passage also covers borrowings
    # A ticker filter and kind filter narrow both rankings.
    iid = instrument_ids(session, ["INFY.NS"])["INFY.NS"]
    only = retrieve.retrieve(session, "profitability", as_of=when, instrument_id=iid,
                             embedder=fake)  # fmt: skip
    assert {p.document.id for p in only.passages} == {corpus["infy"]}
    # Both rankings agreeing beats either alone.
    both = retrieve.retrieve(session, "margin", as_of=when, embedder=fake)
    assert both.passages[0].keyword_rank == 1 and both.passages[0].vector_rank == 1


def test_embedding_failure_falls_back_to_keyword(session: Session, corpus) -> None:
    index_documents(session, embedder=FakeEmbedder())
    got = retrieve.retrieve(
        session, "sales", as_of=datetime(2027, 2, 1), embedder=FakeEmbedder(fail=True)
    )
    assert got.mode == "keyword" and got.passages and "failed" in got.notes[0]


def test_a_new_model_does_not_mix_with_old_vectors(session: Session, corpus) -> None:
    index_documents(session, embedder=FakeEmbedder())

    class Other(FakeEmbedder):
        model = "other-embed"

    got = retrieve.retrieve(session, "topline", as_of=datetime(2027, 2, 1), embedder=Other())
    assert got.passages == [] and "No passage is embedded with other-embed" in got.notes[-1]
    report = index_documents(session, embedder=Other(), max_embed=2)
    assert report.chunks_embedded == 2 and report.chunks_waiting == 1


def test_ollama_embedder_shape_prefixes_and_errors() -> None:
    sent: list[dict] = []

    def post(url: str, body: dict, timeout: float) -> httpx.Response:
        sent.append({"url": url, **body})
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2] for _ in body["input"]]})

    e = OllamaEmbedder(model="nomic-embed-text", url="http://h:1/", post=post)
    assert e.embed(["a", "b"], "document") == [[0.1, 0.2], [0.1, 0.2]]
    assert sent[0]["url"] == "http://h:1/api/embed"
    assert sent[0]["input"] == ["search_document: a", "search_document: b"]
    e.embed(["q"], "query")
    assert sent[1]["input"] == ["search_query: q"]
    plain = OllamaEmbedder(model="mxbai-embed-large", post=post)
    plain.embed(["x"], "query")
    assert sent[2]["input"] == ["x"]

    def bad(status: int, payload) -> OllamaEmbedder:
        return OllamaEmbedder(model="m", post=lambda *_: httpx.Response(status, json=payload))

    with pytest.raises(AiProviderError, match="HTTP 500"):
        bad(500, {}).embed(["x"], "query")
    with pytest.raises(AiProviderError, match="wrong number"):
        bad(200, {"embeddings": []}).embed(["x"], "query")
    with pytest.raises(AiProviderError, match="not numbers"):
        bad(200, {"embeddings": [["a"]]}).embed(["x"], "query")

    def down(*_):
        raise httpx.ConnectError("refused")

    with pytest.raises(AiProviderError, match="not reachable"):
        OllamaEmbedder(model="m", post=down).embed(["x"], "query")


def test_route(client: TestClient, session: Session, corpus, monkeypatch) -> None:
    monkeypatch.setattr("stockviz.routers.documents.embedder_from_settings", lambda _s: None)
    res = client.get("/v1/documents/passages", params={"q": "borrowings", "ticker": "tcs.ns"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "keyword" and body["embed_model"] is None
    assert body["passages"][0]["document"]["ticker"] == "TCS.NS"
    assert "reciprocal rank fusion" in body["method"]
    assert client.get("/v1/documents/passages", params={"q": "x"}).status_code == 422
    assert (
        client.get("/v1/documents/passages", params={"q": "sales", "ticker": "NOPE"}).status_code
        == 404
    )

    fake = FakeEmbedder()
    index_documents(session, embedder=fake)
    monkeypatch.setattr("stockviz.routers.documents.embedder_from_settings", lambda _s: fake)
    res = client.get("/v1/documents/passages", params={"q": "leverage"})
    assert res.json()["mode"] == "hybrid" and res.json()["embed_model"] == "fake-embed"
    assert res.json()["passages"][0]["document"]["title"] == "TCS Q2"
    json.dumps(res.json())


def test_cli_needs_a_model_for_embed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: type("S", (), {"ollama_embed_model": ""})())
    assert cli.main(["docs-index", "--embed"]) == 2
    assert "OLLAMA_EMBED_MODEL" in capsys.readouterr().err
