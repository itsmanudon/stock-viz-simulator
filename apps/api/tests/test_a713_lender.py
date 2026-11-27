"""A7.13 (M5.2): lender mode on planted peers."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Symbol, SymbolMetrics
from stockviz.services import lender

# ROE in percent; P/B on the line 0.5 + 0.1 x ROE.
PEERS = {
    "HDFCBANK.NS": 16,
    "ICICIBANK.NS": 18,
    "AXISBANK.NS": 14,
    "KOTAKBANK.NS": 13,
    "SBIN.NS": 19,
}


def _add(session: Session, ticker: str, sector: str, pb: float | None, roe: float | None) -> None:
    session.add(Symbol(ticker=ticker, name=ticker, currency="INR", sector=sector))
    session.commit()
    session.add(SymbolMetrics(ticker=ticker, pb=pb, roe=roe, as_of=date(2026, 11, 26)))
    session.commit()


def _seed(session: Session) -> None:
    for t, roe in PEERS.items():
        _add(session, t, "Financial Services", 0.5 + 0.1 * roe, roe)
    _add(session, "BANDHANBNK.NS", "Financial Services", 1.0, 15)  # line says 2.0
    _add(session, "TCS.NS", "Technology", 12.0, 45)
    _add(session, "AAPL", "Financial Services", 9.0, 50)  # another market


def test_peer_line_and_gap(session: Session) -> None:
    _seed(session)
    view = lender.lender_view(session, "BANDHANBNK.NS")
    assert view.market == "IN"
    assert [p.ticker for p in view.peers] == sorted([*PEERS, "BANDHANBNK.NS"])
    # Six points: five on the line, one below it, so the fit moves a little.
    assert view.slope is not None and view.line_pb is not None and view.gap is not None
    assert view.gap < -0.5
    assert view.justified_pb == pytest.approx((0.15 - 0.06) / (0.12 - 0.06))


def test_formula_and_refusals(session: Session) -> None:
    assert lender.justified_pb(18, 0.12, 0.06) == pytest.approx(2.0)
    assert lender.justified_pb(18, 0.05, 0.06) is None
    assert lender.peer_line([lender.Peer("A", 1, 10)] * 4) is None
    _seed(session)
    with pytest.raises(lender.NotALender, match="Technology"):
        lender.lender_view(session, "TCS.NS")
    custom = lender.lender_view(session, "SBIN.NS", coe=0.05, growth=0.06)
    assert custom.justified_pb is None and any("cost of equity" in r for r in custom.reasons)


def test_route(client: TestClient, session: Session) -> None:
    _seed(session)
    out = client.get("/v1/symbols/SBIN.NS/lender").json()
    assert out["coe"] == 0.12 and out["growth"] == 0.06
    assert len(out["peers"]) == 6 and "GNPA" in out["kpi_note"]
    assert out["line_pb"] is not None and "least squares" in out["method"]
    assert client.get("/v1/symbols/TCS.NS/lender").status_code == 409
    assert client.get("/v1/symbols/NOPE/lender").status_code == 404
