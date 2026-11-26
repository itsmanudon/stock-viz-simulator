"""A7.9 (M6.2, M6.5): GEX/DEX and key levels, and the payoff what-if."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.models.option_quote import OptionChainQuote
from stockviz.services.instruments import instrument_ids
from stockviz.services.options import exposure as ex
from stockviz.services.options.pricing import black_scholes
from tests.symbols import seed_symbols
from tests.test_options_payoff_book import EXPIRY, _account, option_clock  # noqa: F401

ON = date(2026, 11, 20)
EXP = date(2026, 12, 18)
CHAIN = [
    ex.Contract(EXP, 90.0, "put", 0.35, 5000),
    ex.Contract(EXP, 100.0, "call", 0.30, 1000),
    ex.Contract(EXP, 100.0, "put", 0.30, 1200),
    ex.Contract(EXP, 110.0, "call", 0.28, 6000),
]


def test_gex_and_dex_per_strike_by_hand() -> None:
    out = ex.exposure_from("ACME", CHAIN, 100.0, ON, 0.04, skipped=2)
    years = (EXP - ON).days / 365
    rows = {r["strike"]: r for r in out.strikes}
    p = black_scholes(spot=100.0, strike=110.0, time_to_expiry_years=years, volatility=0.28,
                      risk_free_rate=0.04, option_type="call")  # fmt: skip
    assert rows[110.0]["gex"] == pytest.approx(p.gamma * 6000 * 100 * 100**2 * 0.01, rel=1e-4)
    assert rows[110.0]["dex"] == pytest.approx(p.delta * 6000 * 100 * 100, rel=1e-4)
    put90 = black_scholes(spot=100.0, strike=90.0, time_to_expiry_years=years, volatility=0.35,
                          risk_free_rate=0.04, option_type="put")  # fmt: skip
    assert rows[90.0]["gex"] == pytest.approx(-put90.gamma * 5000 * 100 * 100**2 * 0.01, rel=1e-4)
    assert (out.call_wall, out.put_wall) == (110.0, 90.0)
    assert out.used == 4 and out.skipped == 2
    # ATM: the nearest expiry's strike closest to spot (100), mean of call and put IV.
    assert out.atm_iv == pytest.approx(0.30)
    assert out.expected_move_1d == pytest.approx(100 * 0.30 * math.sqrt(1 / 252), rel=1e-4)


def test_gamma_flip_sits_between_the_put_and_call_walls() -> None:
    out = ex.exposure_from("ACME", CHAIN, 100.0, ON, 0.04, skipped=0)
    assert out.gamma_flip is not None and 90 < out.gamma_flip < 110
    below = ex.total_gex_at(CHAIN, out.gamma_flip - 2, ON, 0.04)
    above = ex.total_gex_at(CHAIN, out.gamma_flip + 2, ON, 0.04)
    assert below < 0 < above  # puts dominate below, calls above


def test_empty_chain_has_a_reason() -> None:
    out = ex.exposure_from("ACME", [], 100.0, ON, 0.04, skipped=3)
    assert out.reason and out.total_gex is None


def test_route_reads_the_newest_snapshot(session: Session, client: TestClient) -> None:
    seed_symbols(session, "ACME", currency="USD")
    session.add(PriceBar(ticker="ACME", ts=datetime(2026, 11, 20), interval="1d", open=Decimal(100),
                         high=Decimal(100), low=Decimal(100), close=Decimal(100), volume=1,
                         source="test"))  # fmt: skip
    iid = instrument_ids(session, ["ACME"])["ACME"]
    for snap in (date(2026, 11, 19), ON):
        for c in CHAIN:
            session.add(OptionChainQuote(instrument_id=iid, snapshot_date=snap, expiry=c.expiry,
                                         strike=Decimal(str(c.strike)), option_type=c.option_type,
                                         implied_volatility=c.iv,
                                         open_interest=c.oi if snap == ON else 1))  # fmt: skip
    session.add(
        OptionChainQuote(
            instrument_id=iid, snapshot_date=ON, expiry=EXP, strike=Decimal(120), option_type="call"
        )
    )  # no IV or OI: skipped
    session.commit()
    body = client.get("/v1/options/ACME/exposure").json()
    assert body["snapshot_date"] == ON.isoformat() and body["spot"] == 100.0
    assert body["call_wall"] == 110.0 and body["skipped"] == 1 and "not direction" in body["note"]
    assert client.get("/v1/options/NOPE/exposure").status_code == 404


def test_payoff_what_if(session: Session, client: TestClient) -> None:
    _account(session)
    body = {"kind": "iron_condor", "ticker": "AAPL", "strikes": ["90", "95", "110", "115"],
            "expiry": EXPIRY.isoformat(), "quantity": 1}  # fmt: skip
    plain = client.post("/v1/options/strategies/payoff", json=body).json()
    assert all(p["what_if"] is None for p in plain["points"])
    same = client.post("/v1/options/strategies/payoff?days_forward=0", json=body).json()
    assert all(p["what_if"] == p["today"] for p in same["points"])
    shocked = client.post("/v1/options/strategies/payoff?days_forward=0&iv_shift=0.2",
                          json=body).json()  # fmt: skip
    mid = min(shocked["points"], key=lambda p: abs(p["spot"] - 102))
    assert mid["what_if"] < mid["today"]  # a short-vol condor loses when IV jumps
    late = client.post("/v1/options/strategies/payoff?days_forward=3650", json=body).json()
    assert all(p["what_if"] == pytest.approx(p["at_expiry"], abs=0.01) for p in late["points"])
