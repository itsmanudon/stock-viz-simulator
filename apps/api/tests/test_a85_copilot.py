"""A8.5 (M11.2): the filings copilot answers from passages and its citations are checked."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.ai import copilot
from stockviz.services.ai.provider import AiProviderError, Message
from tests.test_a84_hybrid_search import FakeEmbedder, _doc, corpus  # noqa: F401
from tests.test_drills import _auth, _user


class FakeModel:
    name = "ollama"
    model = "fake-llm"

    def __init__(self, reply: str = "", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.seen: list[list[Message]] = []

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        self.seen.append(messages)
        if self.fail:
            raise AiProviderError("Ollama is not reachable (ConnectError)")
        return self.reply


def test_check_citations() -> None:
    c = copilot.check_citations("Sales grew nine percent [1]. Debt was repaid [2, 3].", 3)
    assert c.cited == [1, 2, 3] and c.invalid == [] and c.uncited_sentences == 0 and c.grounded
    c = copilot.check_citations(
        "Sales grew nine percent in the quarter [4]. Also margins rose a lot.", 2
    )
    assert c.cited == [] and c.invalid == [4] and not c.grounded and c.uncited_sentences == 1
    # Decimals do not end a sentence; a citation after the full stop belongs to it.
    c = copilot.check_citations(
        "The operating margin was 24.6 percent [1]. Order book was 10.2 billion. [2]", 2
    )
    assert c.uncited_sentences == 0 and c.cited == [1, 2]
    assert copilot.sentences("A b c 1.5 d. [1] E f g h.") == ["A b c 1.5 d. [1]", "E f g h."]
    c = copilot.check_citations(copilot.NOT_FOUND, 2)
    assert not c.grounded and c.uncited_sentences == 0


def test_ask_sends_numbered_sources_and_rules(session: Session, corpus) -> None:  # noqa: F811
    model = FakeModel("Sales grew nine percent in the quarter [1].")
    out = copilot.ask(
        session, model, "  how did   sales do ", as_of=datetime(2027, 2, 1),
        ticker_names=lambda ids: dict.fromkeys(ids, "TCS.NS"),
    )  # fmt: skip
    assert out.question == "how did sales do" and out.check and out.check.grounded
    system, user = model.seen[0]
    assert system.role == "system" and "Never recommend buying" in system.content
    assert copilot.NOT_FOUND in system.content
    assert user.content.startswith("Sources:\n\n[1] TCS.NS · TCS Q2 · public 2026-10-09")
    assert user.content.endswith("Question: how did sales do")
    assert out.warnings == []


def test_no_passage_means_no_model_call(session: Session, corpus) -> None:  # noqa: F811
    model = FakeModel("should not be used")
    out = copilot.ask(session, model, "what about quantum computing", as_of=datetime(2027, 2, 1),
                      ticker_names=lambda ids: {})  # fmt: skip
    assert model.seen == [] and out.answer == copilot.NOT_FOUND and out.check is None
    assert "no model was asked" in out.warnings[0]
    # Point in time: Q3's headcount passage is not public in December 2026.
    out = copilot.ask(session, model, "headcount", as_of=datetime(2026, 12, 1),
                      ticker_names=lambda ids: {})  # fmt: skip
    assert model.seen == []


def test_unsupported_answers_are_flagged(session: Session, corpus) -> None:  # noqa: F811
    out = copilot.ask(
        session, FakeModel("Sales probably doubled next year according to analysts [7]."),
        "sales", as_of=datetime(2027, 2, 1), ticker_names=lambda ids: {},
    )  # fmt: skip
    assert out.check and not out.check.grounded and out.check.invalid == [7]
    assert any("do not exist: [7]" in w for w in out.warnings)
    assert any("cites no source" in w for w in out.warnings)


def test_route(client: TestClient, session: Session, corpus, monkeypatch) -> None:  # noqa: F811
    uid = _user(session, "ask@stockviz.dev")
    body = {"question": "how did borrowings change", "ticker": "TCS.NS"}
    assert client.post("/v1/ai/ask", json=body).status_code == 401
    monkeypatch.setattr("stockviz.routers.ai.embedder_from_settings", lambda _s: None)

    class Off:
        ollama_model = ""

    monkeypatch.setattr("stockviz.routers.ai.get_settings", lambda: Off())
    assert client.post("/v1/ai/ask", json=body, headers=_auth(uid)).status_code == 409

    model = FakeModel("Borrowings were repaid in full [1].")
    monkeypatch.setattr("stockviz.routers.ai.provider_from_settings", lambda _s: model)
    res = client.post("/v1/ai/ask", json=body, headers=_auth(uid))
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["grounded"] and got["cited"] == [1] and got["retrieval_mode"] == "keyword"
    assert (
        got["sources"][0]["cited"]
        and got["sources"][0]["passage"]["document"]["ticker"] == "TCS.NS"
    )
    assert got["model"] == "fake-llm" and "Not investment advice" in got["disclaimer"]

    other = {"question": "how did borrowings change", "ticker": "NOPE"}
    assert client.post("/v1/ai/ask", json=other, headers=_auth(uid)).status_code == 404
    assert client.post("/v1/ai/ask", json={"question": "hi"}, headers=_auth(uid)).status_code == 422
    monkeypatch.setattr(
        "stockviz.routers.ai.provider_from_settings", lambda _s: FakeModel(fail=True)
    )
    assert client.post("/v1/ai/ask", json=body, headers=_auth(uid)).status_code == 502
