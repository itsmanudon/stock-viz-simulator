"""A9.4 (M6.3): term structure, skew, VRP and IV rank, by hand."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.models.option_quote import OptionChainQuote
from stockviz.services.instruments import instrument_ids
from stockviz.services.options import vol_summary as vs
from tests.symbols import seed_symbols

ON = date(2026, 11, 20)


def _chain(on: date, atm: float) -> list[vs.Quote]:
    near, far = on + timedelta(days=28), on + timedelta(days=90)
    out: list[vs.Quote] = []
    for expiry, bump in ((near, 0.0), (far, 0.02)):
        for strike, extra in (
            (85.0, 0.06),
            (95.0, 0.02),
            (100.0, 0.0),
            (105.0, -0.01),
            (115.0, -0.02),
        ):
            for kind in ("call", "put"):
                out.append(vs.Quote(expiry, strike, kind, atm + bump + extra))
    return out


def test_term_structure_and_skew() -> None:
    closes = {ON - timedelta(days=i): 100.0 for i in range(40)}
    out = vs.summarise("ACME", {ON: _chain(ON, 0.30)}, closes, 0.04)
    assert [t["days"] for t in out.term] == [28, 90]
    assert out.term[0]["atm_iv"] == pytest.approx(0.30)
    assert out.term[1]["atm_iv"] == pytest.approx(0.32)
    skew = out.term[0]["skew_25d"]
    assert isinstance(skew, float) and skew > 0  # puts dearer
    assert out.atm_30d == pytest.approx(0.30)  # the 28-day expiry is nearest 30


def test_vrp_against_realised_volatility() -> None:
    closes: dict[date, float] = {}
    price = 100.0
    for i in range(40):
        price *= math.exp(0.01 if i % 2 else -0.01)  # +-1% a day
        closes[ON - timedelta(days=39 - i)] = price
    out = vs.summarise("ACME", {ON: _chain(ON, 0.30)}, closes, 0.04)
    window = [closes[d] for d in sorted(closes)][-22:]
    rets = [math.log(b / a) for a, b in pairwise(window)]
    mean = sum(rets) / len(rets)
    rv = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) * 252)
    assert out.realised_21d == pytest.approx(rv, abs=1e-6)  # rounded to 6 places
    assert out.vrp == pytest.approx(0.30 - rv, abs=2e-6)


def test_iv_rank_needs_20_snapshots() -> None:
    closes = {ON - timedelta(days=i): 100.0 for i in range(400)}
    few = {ON - timedelta(days=i): _chain(ON - timedelta(days=i), 0.2 + i / 100) for i in range(5)}
    assert vs.summarise("ACME", few, closes, 0.04).iv_rank is None
    many = {
        ON - timedelta(days=i): _chain(ON - timedelta(days=i), 0.20 + i / 100) for i in range(30)
    }
    out = vs.summarise("ACME", many, closes, 0.04)
    # Today's 0.20 is the lowest of the year: rank 0, percentile 1/30.
    assert out.iv_rank == 0.0 and out.iv_percentile == pytest.approx(1 / 30, abs=1e-4)


def test_no_chain_has_a_reason() -> None:
    assert vs.summarise("ACME", {}, {}, 0.04).reason


def test_route(session: Session, client: TestClient) -> None:
    seed_symbols(session, "ACME", currency="USD")
    for i in range(30):
        session.add(PriceBar(ticker="ACME", ts=datetime(2026, 10, 22) + timedelta(days=i),
                             interval="1d", open=Decimal(100), high=Decimal(100), low=Decimal(100),
                             close=Decimal(100), volume=1, source="test"))  # fmt: skip
    iid = instrument_ids(session, ["ACME"])["ACME"]
    for q in _chain(ON, 0.25):
        session.add(OptionChainQuote(instrument_id=iid, snapshot_date=ON, expiry=q.expiry,
                                     strike=Decimal(str(q.strike)), option_type=q.option_type,
                                     implied_volatility=q.iv, open_interest=10))  # fmt: skip
    session.commit()
    body = client.get("/v1/options/ACME/vol-summary").json()
    assert body["snapshot_date"] == ON.isoformat() and len(body["term"]) == 2
    assert body["atm_30d"] == pytest.approx(0.25) and body["iv_rank"] is None
    assert "not a signal" in body["method"]
