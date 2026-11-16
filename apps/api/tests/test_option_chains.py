"""Phase 9.6: option-chain snapshots, their implied volatility, and pricing from it.

No network: chains are built here at a known volatility and fed through the
same code the nightly job uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import OptionChainQuote, OptionType
from stockviz.services.options.chains import (
    ChainRow,
    chain_volatility,
    snapshot_all,
    store_snapshot,
)
from stockviz.services.options.pricing import black_scholes
from stockviz.services.options.trade import RISK_FREE_RATE, quote_option
from tests.test_option_short_legs import PRICES
from tests.test_options import TODAY, _seed_bars

D = Decimal
SNAP = TODAY - timedelta(days=1)  # the snapshot is from the last close
EXP1 = TODAY + timedelta(days=25)
EXP2 = TODAY + timedelta(days=60)


@pytest.fixture(autouse=True)
def option_clock(monkeypatch):
    monkeypatch.setattr("stockviz.services.options.trade.utcnow", lambda: datetime(2026, 8, 24, 18))


def _chain(spot: float, vol_by_strike, expiries=(EXP1, EXP2), spread: float = 0.10):
    """A listed chain priced at a known volatility, quoted as bid/ask around it."""
    rows = []
    for expiry in expiries:
        years = (expiry - SNAP).days / 365
        for strike, vol in vol_by_strike.items():
            for kind in ("call", "put"):
                mid = black_scholes(
                    spot=spot, strike=strike, time_to_expiry_years=years, volatility=vol,
                    risk_free_rate=RISK_FREE_RATE, option_type=kind,
                ).value  # fmt: skip
                rows.append(
                    ChainRow(
                        expiry=expiry, strike=D(str(strike)), option_type=kind,
                        bid=D(str(round(mid - spread / 2, 6))),
                        ask=D(str(round(mid + spread / 2, 6))), last=None,
                    )
                )  # fmt: skip
    return rows


def _seeded(session: Session) -> None:
    _seed_bars(session, PRICES, end=SNAP)  # spot 104


def test_a_snapshot_stores_each_contract_with_its_implied_volatility(session: Session) -> None:
    _seeded(session)
    rows = _chain(104, {95: 0.32, 105: 0.28, 115: 0.30})
    assert store_snapshot(session, "AAPL", rows, snapshot_date=SNAP) == len(rows)
    stored = session.exec(select(OptionChainQuote)).all()
    by_key = {(r.expiry, r.strike, r.option_type): r for r in stored}
    atm = by_key[(EXP1, D(105), "call")]
    assert atm.price == ((atm.bid or 0) + (atm.ask or 0)) / 2
    assert atm.implied_volatility == pytest.approx(0.28, abs=1e-6)
    assert by_key[(EXP2, D(95), "put")].implied_volatility == pytest.approx(0.32, abs=1e-6)
    # A rerun the same day replaces the day's rows.
    store_snapshot(session, "AAPL", rows, snapshot_date=SNAP)
    assert len(session.exec(select(OptionChainQuote)).all()) == len(rows)


def test_a_contract_with_no_price_is_kept_without_an_iv(session: Session) -> None:
    _seeded(session)
    row = ChainRow(expiry=EXP1, strike=D(150), option_type="call", bid=None, ask=None, last=None)
    expired = ChainRow(
        expiry=SNAP, strike=D(100), option_type="call", bid=D(1), ask=D(2), last=None
    )
    assert store_snapshot(session, "AAPL", [row, expired], snapshot_date=SNAP) == 1
    (kept,) = session.exec(select(OptionChainQuote)).all()
    assert (kept.price, kept.implied_volatility) == (None, None)


def test_pricing_uses_the_nearest_listed_contracts_iv(session: Session) -> None:
    _seeded(session)
    store_snapshot(session, "AAPL", _chain(104, {100: 0.35, 110: 0.25}), snapshot_date=SNAP)
    chain = chain_volatility(
        session, "AAPL", option_type="call", strike=D(108), expiry=EXP1 + timedelta(days=3),
        asof=TODAY,
    )  # fmt: skip
    assert chain is not None
    assert (chain.expiry, chain.strike) == (EXP1, D(110))
    assert chain.volatility == pytest.approx(0.25, abs=1e-6)
    quote = quote_option(
        session, ticker="AAPL", option_type=OptionType.CALL, strike=D(108),
        expiry=EXP1 + timedelta(days=3),
    )  # fmt: skip
    assert quote.volatility == pytest.approx(0.25, abs=1e-6)
    assert quote.volatility_method.startswith("implied volatility from the 2026-08-23")


def test_pricing_falls_back_when_no_contract_is_close_enough(session: Session) -> None:
    _seeded(session)
    store_snapshot(session, "AAPL", _chain(104, {100: 0.35}), snapshot_date=SNAP)
    far_strike = chain_volatility(
        session, "AAPL", option_type="call", strike=D(130), expiry=EXP1, asof=TODAY
    )
    far_expiry = chain_volatility(
        session, "AAPL", option_type="call", strike=D(100), expiry=TODAY + timedelta(days=200),
        asof=TODAY,
    )  # fmt: skip
    stale = chain_volatility(
        session, "AAPL", option_type="call", strike=D(100), expiry=EXP1,
        asof=TODAY + timedelta(days=9),
    )  # fmt: skip
    assert (far_strike, far_expiry, stale) == (None, None, None)
    quote = quote_option(
        session, ticker="AAPL", option_type=OptionType.CALL, strike=D(130), expiry=EXP1
    )
    assert quote.volatility_method.startswith("historical volatility")


def test_one_failing_ticker_does_not_stop_the_rest(session: Session) -> None:
    _seeded(session)

    def fetch(ticker: str):
        if ticker == "BAD":
            raise RuntimeError("no options listed")
        return _chain(104, {105: 0.3}, expiries=(EXP1,))

    stored, failed = snapshot_all(
        session, ["BAD", "AAPL"], snapshot_date=SNAP, fetch=fetch, pause_seconds=0
    )
    assert (stored, failed) == (2, ["BAD"])


def test_the_job_fails_only_when_every_ticker_failed(session: Session, monkeypatch) -> None:
    monkeypatch.setattr(cli, "engine", session.get_bind())

    def broken(_ticker: str):
        raise RuntimeError("provider down")

    monkeypatch.setattr(cli, "fetch_option_chain", broken)
    monkeypatch.setattr("stockviz.services.options.chains._time.sleep", lambda _s: None)
    _seeded(session)
    assert cli.main(["options-snapshot", "AAPL"]) == 1
    monkeypatch.setattr(cli, "fetch_option_chain", lambda _t: [])
    assert cli.main(["options-snapshot", "AAPL"]) == 0


def test_surface_endpoint(session: Session, client: TestClient) -> None:
    _seeded(session)
    empty = client.get("/v1/options/surface", params={"ticker": "AAPL"}).json()
    assert empty["snapshot_date"] is None and empty["expiries"] == []
    store_snapshot(session, "AAPL", _chain(104, {95: 0.33, 105: 0.27}), snapshot_date=SNAP)
    body = client.get("/v1/options/surface", params={"ticker": "aapl"}).json()
    assert body["snapshot_date"] == SNAP.isoformat()
    assert [e["expiry"] for e in body["expiries"]] == [EXP1.isoformat(), EXP2.isoformat()]
    first = body["expiries"][0]["points"]
    assert [p["strike"] for p in first] == ["95.000000", "105.000000"]
    assert first[0]["put_iv"] == pytest.approx(0.33, abs=1e-6)
