"""A9.11 (M11.4, M11.5): the research grid and the case for / against."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.ai import research
from stockviz.services.ai.provider import Message
from tests.symbols import seed_symbols
from tests.test_a84_hybrid_search import _doc
from tests.test_drills import _auth, _user


class SideModel:
    """Answers each side differently so the test can tell them apart."""

    name = "ollama"
    model = "fake-llm"

    def __init__(self) -> None:
        self.systems: list[str] = []
        self.users: list[str] = []

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        self.systems.append(messages[0].content)
        self.users.append(messages[1].content)
        if "case FOR" in messages[0].content:
            return "Sales grew nine percent in the quarter [1]. A slowdown would weaken this [1]."
        if "case AGAINST" in messages[0].content:
            return "Borrowings had to be repaid in full this quarter [1]. More orders would weaken this."
        return "Sales grew nine percent [1]."


def _corpus(session: Session) -> None:
    seed_symbols(session, "TCS.NS", "INFY.NS", currency="INR")
    _doc(session, "TCS.NS", "TCS Q2", "Sales grew nine percent. Borrowings were repaid in full.",
         datetime(2026, 10, 9))  # fmt: skip
    _doc(session, "INFY.NS", "INFY Q2", "Margin widened to 21 percent.", datetime(2026, 10, 9))


def test_grid_cells_cite_only_their_own_company(session: Session) -> None:
    _corpus(session)
    from stockviz.services.instruments import instrument_ids

    ids = instrument_ids(session, ["TCS.NS", "INFY.NS"])
    model = SideModel()
    cells = research.grid(
        session, model, [("TCS.NS", ids["TCS.NS"]), ("INFY.NS", ids["INFY.NS"])],
        ["sales growth", "margin"], as_of=datetime(2027, 1, 1), ticker_names=lambda i: {},
    )  # fmt: skip
    assert [(c.ticker, c.question) for c in cells] == [
        ("TCS.NS", "sales growth"), ("TCS.NS", "margin"), ("INFY.NS", "sales growth"),
        ("INFY.NS", "margin"),
    ]  # fmt: skip
    for c in cells:
        assert all(p.document.instrument_id == ids[c.ticker] for p in c.answer.sources)
    # TCS has no "margin" passage and INFY no "sales" one: no model call for those cells.
    assert len(model.users) == 2


def test_debate_uses_the_same_sources_for_both_sides(session: Session) -> None:
    _corpus(session)
    from stockviz.services.instruments import instrument_ids

    iid = instrument_ids(session, ["TCS.NS"])["TCS.NS"]
    model = SideModel()
    d = research.debate(session, model, "TCS.NS", iid, "sales and borrowings",
                        as_of=datetime(2027, 1, 1), ticker_names=lambda i: {})  # fmt: skip
    assert len(model.users) == 2 and model.users[0] == model.users[1]
    assert "case FOR" in model.systems[0] and "case AGAINST" in model.systems[1]
    assert all("Never recommend buying" in s for s in model.systems)
    assert d.case_for.check and d.case_for.check.grounded and not d.case_for.warnings
    # The against side left one sentence uncited.
    assert d.case_against.check and d.case_against.check.uncited_sentences == 1
    empty = research.debate(session, SideModel(), "TCS.NS", iid, "quantum computing roadmap",
                            as_of=datetime(2027, 1, 1), ticker_names=lambda i: {})  # fmt: skip
    assert (
        empty.case_for.answer == research.NO_CASE and empty.case_against.answer == research.NO_CASE
    )


def test_routes(client: TestClient, session: Session, monkeypatch) -> None:
    _corpus(session)
    uid = _user(session, "g@stockviz.dev")
    h = _auth(uid)
    monkeypatch.setattr("stockviz.routers.ai.provider_from_settings", lambda _s: SideModel())
    monkeypatch.setattr("stockviz.routers.ai.embedder_from_settings", lambda _s: None)
    body = {"tickers": ["tcs.ns", "INFY.NS", "TCS.NS"], "questions": ["sales growth"]}
    assert client.post("/v1/ai/grid", json=body).status_code == 401
    res = client.post("/v1/ai/grid", json=body, headers=h)
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["tickers"] == ["TCS.NS", "INFY.NS"] and len(got["cells"]) == 2
    assert got["model_calls"] == 1 and got["cells"][0]["result"]["grounded"]
    assert (
        client.post("/v1/ai/grid", json={**body, "tickers": ["NOPE"]}, headers=h).status_code == 404
    )
    long = {"tickers": ["TCS.NS"], "questions": ["a", "b", "c", "d"]}
    assert client.post("/v1/ai/grid", json=long, headers=h).status_code == 422
    short = {"tickers": ["TCS.NS"], "questions": ["hey"]}
    assert client.post("/v1/ai/grid", json=short, headers=h).status_code == 422

    res = client.post("/v1/ai/debate", json={"ticker": "TCS.NS", "topic": "sales and borrowings"},
                      headers=h)  # fmt: skip
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["case_for"]["grounded"] and "Borrowings" in got["case_against"]["answer"]
    assert got["case_for"]["sources"] == got["case_against"]["sources"]
    assert "not investment advice" in got["disclaimer"]
