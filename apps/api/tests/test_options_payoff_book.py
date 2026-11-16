"""Phase 9.5: payoff curves, the chance of profit, and the options book."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from statistics import NormalDist

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import OptionType, StrategyKind
from stockviz.services.options.payoff import strategy_payoff
from stockviz.services.options.strategies import open_strategy, quote_strategy
from stockviz.services.options.trade import RISK_FREE_RATE, value_option
from tests.test_option_strategies import EXPIRY, FAR, _account
from tests.test_options import _auth_headers

D = Decimal


@pytest.fixture(autouse=True)
def option_clock(monkeypatch):
    monkeypatch.setattr("stockviz.services.options.trade.utcnow", lambda: datetime(2026, 8, 24, 18))


def _quote(session: Session, kind: StrategyKind, strikes: list[str], **kw):
    return quote_strategy(
        session, kind=kind, ticker="AAPL", strikes=[D(k) for k in strikes],
        expiry=kw.pop("expiry", EXPIRY), quantity=kw.pop("quantity", 1), **kw,
    )  # fmt: skip


def test_a_bull_call_payoff_is_flat_beyond_its_strikes(session: Session) -> None:
    _account(session)
    quote = _quote(session, StrategyKind.BULL_CALL, ["100", "110"])
    payoff = strategy_payoff(quote)
    debit = float(quote.risk.max_loss)
    assert quote.risk.max_gain is not None
    gain = float(quote.risk.max_gain)
    for p in payoff.points:
        if p.spot <= 100:
            assert p.at_expiry == pytest.approx(-debit, abs=0.01)
        if p.spot >= 110:
            assert p.at_expiry == pytest.approx(gain, abs=0.01)
    # Priced at the model: today's curve is about zero at today's close.
    spot = float(quote.legs[0][1].spot)
    nearest = min(payoff.points, key=lambda p: abs(p.spot - spot))
    assert abs(nearest.today) < 5


def test_the_chance_of_profit_matches_the_closed_form(session: Session) -> None:
    """A bull call spread profits exactly above its breakeven, so the chance is
    N((ln(S/B) + (r - s^2/2) T) / (s sqrt T)) for a lognormal price."""
    _account(session)
    quote = _quote(session, StrategyKind.BULL_CALL, ["100", "110"])
    payoff = strategy_payoff(quote)
    first = quote.legs[0][1]
    s, vol = float(first.spot), first.volatility
    t = (EXPIRY - datetime(2026, 8, 24).date()).days / 365
    (breakeven,) = quote.risk.breakevens
    d = (math.log(s / float(breakeven)) + (RISK_FREE_RATE - vol * vol / 2) * t) / (
        vol * math.sqrt(t)
    )
    assert payoff.prob_profit == pytest.approx(NormalDist().cdf(d), abs=0.005)


def test_a_covered_call_payoff_counts_its_shares(session: Session) -> None:
    _account(session, shares=100)
    quote = _quote(session, StrategyKind.COVERED_CALL, ["110"])
    payoff = strategy_payoff(quote)
    premium = float(quote.legs[0][1].premium)
    spot = float(quote.legs[0][1].spot)
    at = {p.spot: p.at_expiry for p in payoff.points}
    # Above the strike the gain is capped: (110 - spot) x 100 + premium.
    top = max(at)
    assert at[top] == pytest.approx((110 - spot) * 100 + premium, abs=0.01)


def test_a_calendar_is_charted_to_its_near_expiry(session: Session) -> None:
    _account(session)
    quote = _quote(
        session, StrategyKind.CALENDAR, ["105"], far_expiry=FAR, option_type=OptionType.CALL
    )
    payoff = strategy_payoff(quote)
    assert payoff.horizon == EXPIRY
    best = max(payoff.points, key=lambda p: p.at_expiry)
    assert best.spot == pytest.approx(105, abs=3)  # a calendar earns most near its strike


def test_payoff_endpoint(session: Session, client: TestClient) -> None:
    _account(session)
    body = {"kind": "iron_condor", "ticker": "AAPL", "strikes": ["90", "95", "110", "115"],
            "expiry": EXPIRY.isoformat(), "quantity": 1}  # fmt: skip
    r = client.post("/v1/options/strategies/payoff", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["quote"]["label"] == "Iron condor"
    assert len(out["points"]) >= 81
    assert 0 < out["prob_profit"] < 1
    assert "lognormal" in out["method"]


def test_the_book_sums_greeks_and_states_each_expiry(session: Session, client: TestClient) -> None:
    user_id, _ = _account(session, shares=100)  # spot 104
    open_strategy(session, user_id=user_id, kind=StrategyKind.BULL_CALL, ticker="AAPL",
                  strikes=[D(100), D(110)], expiry=EXPIRY, quantity=1)  # fmt: skip
    open_strategy(session, user_id=user_id, kind=StrategyKind.COVERED_CALL, ticker="AAPL",
                  strikes=[D(110)], expiry=EXPIRY, quantity=1)  # fmt: skip
    from sqlmodel import select

    from stockviz.models import OptionsPosition
    from stockviz.models.option import position_sign

    expected = sum(
        value_option(session, leg).delta * 100 * position_sign(leg)
        for leg in session.exec(select(OptionsPosition)).all()
    )
    body = client.get("/v1/options/book", headers=_auth_headers(user_id)).json()
    (aapl,) = body["underlyings"]
    assert aapl["delta_shares"] == pytest.approx(expected, abs=1e-3)
    assert body["dollar_delta"] == pytest.approx(expected * 104, abs=0.05)
    (group,) = body["expirations"]
    assert group["expiry"] == EXPIRY.isoformat()
    spread, covered = group["items"]
    assert spread["label"] == "Bull call spread"
    assert spread["outcome"] == "Settles in cash: net +400.00"  # the 100 call is 4 in the money
    assert covered["outcome"] == "Expires; the premium is kept and the shares released"
    assert covered["at_risk"] is None
    assert client.get("/v1/options/book").status_code == 401
