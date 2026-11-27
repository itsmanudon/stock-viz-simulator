"""A9.10 (M11.3): what changed between filings, hedging, and verified figures."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.ai import extract as ex
from stockviz.services.documents import compare as cmp
from tests.symbols import seed_symbols
from tests.test_a84_hybrid_search import _doc
from tests.test_a85_copilot import FakeModel
from tests.test_drills import _auth, _user

RISK_2025 = """Table of contents
Item 1A. Risk Factors ........ 12
Item 2. Properties ........ 30

Item 1. Business
We make widgets for industrial customers across forty countries worldwide.

Item 1A. Risk Factors

Our revenue depends on a small number of large customers in North America.

Supply of rare earth magnets comes from a single supplier and may be interrupted.

Interest rate increases could raise our borrowing costs over the next few years.

Item 1B. Unresolved Staff Comments
None.
"""

RISK_2026 = """Item 1. Business
We make widgets for industrial customers across forty-two countries worldwide.

Item 1A. Risk Factors

Our revenue depends on a small number of large customers in North America and Europe.

Interest rate increases could raise our borrowing costs over the next few years.

New export controls on semiconductors may restrict sales to some of our customers.

Item 2. Properties
A plant in Ohio.
"""


def test_risk_factor_section_skips_the_table_of_contents() -> None:
    body = cmp.risk_factors(RISK_2025)
    assert body is not None and body.startswith("Item 1A. Risk Factors\n\nOur revenue")
    assert "Unresolved" not in body and "widgets" not in body
    assert cmp.risk_factors("No such heading here, just text about the business.") is None


def test_compare_finds_added_removed_and_changed_risks() -> None:
    out = cmp.compare(RISK_2025, RISK_2026)
    assert out.scope == "risk_factors" and out.scope_note is None
    kinds = sorted(c.kind for c in out.changes)
    assert kinds == ["added", "changed", "removed"] and out.unchanged == 1
    changed = next(c for c in out.changes if c.kind == "changed")
    assert "and Europe" in (changed.after or "") and (changed.similarity or 0) > 0.6
    assert "rare earth" in (next(c for c in out.changes if c.kind == "removed").before or "")
    assert "export controls" in (next(c for c in out.changes if c.kind == "added").after or "")
    whole = cmp.compare("A short memo about the plan for the quarter ahead of us.", RISK_2026)
    assert whole.scope == "whole_text" and "earlier" in (whole.scope_note or "")


def test_hedging_rate() -> None:
    h = cmp.hedging("We may see growth. It could possibly improve, going forward, we think.")
    assert h.words == 12 and h.hedges == 5 and h.per_thousand == round(5000 / 12, 2)
    assert dict(h.top)["may"] == 1 and "going forward" in dict(h.top)
    assert cmp.hedging("").per_thousand is None


def test_compare_route(client: TestClient, session: Session) -> None:
    seed_symbols(session, "ACME", "OTHR")
    a = _doc(session, "ACME", "10-K 2025", RISK_2025, datetime(2025, 2, 1))
    b = _doc(session, "ACME", "10-K 2026", RISK_2026, datetime(2026, 2, 1))
    o = _doc(session, "OTHR", "10-K 2026", RISK_2026 + " other", datetime(2026, 2, 1))
    res = client.get(f"/v1/documents/{b}/compare")
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["against"]["id"] == a and got["scope"] == "risk_factors"
    assert (got["added"], got["removed"], got["changed"], got["unchanged"]) == (1, 1, 1, 1)
    assert got["hedging_after"]["hedges"] >= 1 and "not of evasiveness" in got["method"]
    # Explicit order does not matter; the earlier one is "before".
    flipped = client.get(f"/v1/documents/{a}/compare", params={"against": b}).json()
    assert flipped["document"]["id"] == b and flipped["against"]["id"] == a
    first = client.get(f"/v1/documents/{a}/compare").json()
    assert first["against"] is None and "No earlier document" in first["note"]
    assert client.get(f"/v1/documents/{b}/compare", params={"against": o}).status_code == 400
    assert client.get(f"/v1/documents/{b}/compare", params={"against": b}).status_code == 400
    assert client.get("/v1/documents/999/compare").status_code == 404


TRANSCRIPT = (
    "Revenue for the quarter was 64,259 crore, up 6.4 percent year on year.\n\n"
    "Operating margin came in at 24.6 percent, down 30 basis points.\n\n"
    "Management thanked the employees and the customers for their support."
)


def test_extract_keeps_only_figures_found_in_the_text(session: Session) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    did = _doc(session, "TCS.NS", "Q2", TRANSCRIPT, datetime(2026, 10, 9))
    reply = json.dumps([
        {"metric": "Revenue", "value": "64,259", "unit": "crore", "period": "Q2",
         "quote": "Revenue for the quarter was 64,259 crore, up 6.4 percent year on year."},
        {"metric": "Operating margin", "value": "24.6", "unit": "%", "period": "Q2",
         "quote": "operating  margin came in at 24.6 percent, down 30 basis points."},
        {"metric": "Net profit", "value": "12,040", "unit": "crore", "period": "Q2",
         "quote": "Net profit was 12,040 crore."},
        {"metric": "Margin", "value": "25.0", "unit": "%", "period": "Q2",
         "quote": "Operating margin came in at 24.6 percent, down 30 basis points."},
        {"metric": "Revenue", "value": "64,259", "unit": "crore", "period": "Q2",
         "quote": "Revenue for the quarter was 64,259 crore, up 6.4 percent year on year."},
        {"metric": "", "value": "1", "quote": "x"},
    ])  # fmt: skip
    model = FakeModel("```json\n" + reply + "\n```")
    out = ex.extract(session, model, did)
    assert [f.metric for f in out.figures] == ["Revenue", "Operating margin"]
    assert out.dropped == {
        "quote not in the text": 1,
        "value not in its quote": 1,
        "duplicate": 1,
        "incomplete": 1,
    }
    system, user = model.seen[0]
    assert "ONLY a JSON array" in system.content and "Passage 1:" in user.content
    words = _doc(session, "TCS.NS", "Letter", "Thank you to every employee and customer.",
                 datetime(2026, 10, 10))  # fmt: skip
    silent = FakeModel("[]")
    assert ex.extract(session, silent, words).figures == [] and silent.seen == []
    bad = ex.extract(session, FakeModel("Sure! Here are the figures."), did)
    assert bad.figures == [] and bad.dropped == {"answer was not a JSON list": 1}


def test_extract_route(client: TestClient, session: Session, monkeypatch) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    did = _doc(session, "TCS.NS", "Q2", TRANSCRIPT, datetime(2026, 10, 9))
    uid = _user(session, "x@stockviz.dev")
    reply = json.dumps([{"metric": "Revenue", "value": "64,259", "unit": "crore", "period": "Q2",
                         "quote": "Revenue for the quarter was 64,259 crore"}])  # fmt: skip
    monkeypatch.setattr("stockviz.routers.ai.provider_from_settings", lambda _s: FakeModel(reply))
    assert client.post("/v1/ai/extract", json={"document_id": did}).status_code == 401
    res = client.post("/v1/ai/extract", json={"document_id": did}, headers=_auth(uid))
    assert res.status_code == 200, res.text
    got = res.json()
    assert got["figures"][0]["value"] == "64,259" and got["passages_read"] == 1
    assert "word for word" in got["method"] and "Not investment advice" in got["disclaimer"]
    missing = client.post("/v1/ai/extract", json={"document_id": 999}, headers=_auth(uid))
    assert missing.status_code == 404


def test_headline_passages_go_to_the_model_first(session: Session) -> None:
    seed_symbols(session, "AAPL")
    cover = "\n\n".join(
        f"Commission file number 001-{n:05d}. Address line {n}." for n in range(250)
    )
    body = cover + "\n\nTotal net sales were $94,930 million, up 6 percent. Diluted EPS was $1.64."
    did = _doc(session, "AAPL", "10-Q", body, datetime(2026, 10, 9))
    passages = ex.passages_with_numbers(session, did)
    assert len(passages) == ex.MAX_PASSAGES  # the cover alone has more numbered passages
    assert "94,930" in passages[0].text  # the headline passage, last in the text, goes first
    assert "001-00000" not in passages[0].text and "001-00000" in passages[1].text
