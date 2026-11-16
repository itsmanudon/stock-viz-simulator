"""Phase 9.1: rho, implied volatility, the premium floor (LG-14), one trading date (LG-15)."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import PriceBar, Symbol
from stockviz.services.markets.calendar import trading_date
from stockviz.services.options.pricing import (
    MIN_PREMIUM_PER_SHARE,
    ImpliedVolatility,
    black_scholes,
    implied_volatility,
    risk_free_rate,
)

BASE = {"spot": 100.0, "strike": 105.0, "time_to_expiry_years": 0.5, "risk_free_rate": 0.05}


def _iv(price: float, option_type: str, **over: float) -> ImpliedVolatility:
    k = {**BASE, **over}
    return implied_volatility(
        price=price,
        option_type=option_type,
        spot=k["spot"],
        strike=k["strike"],
        time_to_expiry_years=k["time_to_expiry_years"],
        risk_free_rate=k["risk_free_rate"],
    )


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_rho_matches_a_finite_difference(option_type: str) -> None:
    def value(rate: float) -> float:
        return black_scholes(
            **{**BASE, "risk_free_rate": rate}, volatility=0.25, option_type=option_type
        ).value

    priced = black_scholes(**BASE, volatility=0.25, option_type=option_type)
    bump = 1e-5
    numeric = (value(0.05 + bump) - value(0.05 - bump)) / (2 * bump)
    assert priced.rho == pytest.approx(numeric, rel=1e-5)
    assert (priced.rho > 0) is (option_type == "call")


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("vol", [0.05, 0.2, 0.6, 2.5])
def test_implied_volatility_recovers_the_volatility(option_type: str, vol: float) -> None:
    price = black_scholes(**BASE, volatility=vol, option_type=option_type).value
    solved = _iv(price, option_type)
    assert solved.reason is None
    assert solved.volatility == pytest.approx(vol, abs=1e-6)


def test_implied_volatility_says_why_there_is_none() -> None:
    intrinsic = 100.0 - 90.0 * math.exp(-0.05 * 0.5)
    below = _iv(intrinsic - 0.01, "call", strike=90.0)
    assert below.volatility is None and "intrinsic" in (below.reason or "")
    above = _iv(100.5, "call")
    assert above.volatility is None and "bound" in (above.reason or "")
    expired = _iv(1.0, "put", time_to_expiry_years=0.0)
    assert expired.volatility is None and expired.reason == "the contract has expired"


def test_one_rate_per_currency() -> None:
    assert risk_free_rate("usd") == 0.05
    with pytest.raises(KeyError):
        risk_free_rate("INR")


def test_trading_date_is_new_yorks_date() -> None:
    # 02:00 UTC on the 17th is still the evening of the 16th in New York.
    assert trading_date(datetime(2026, 11, 17, 2, tzinfo=UTC)) == date(2026, 11, 16)
    assert trading_date(datetime(2026, 11, 17, 6, tzinfo=UTC)) == date(2026, 11, 17)
    with pytest.raises(ValueError):
        trading_date(datetime(2026, 11, 17, 2))


def test_the_options_service_never_reads_the_utc_date() -> None:
    """LG-15: every 'today' in the options service goes through trading_date."""
    root = Path(__file__).resolve().parents[1] / "src" / "stockviz" / "services" / "options"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"utcnow\(\)\.date\(\)|date\.today\(\)", text), path.name


def _seed(session: Session, *, closes: int, flat: bool = False) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    start = utcnow() - timedelta(days=closes + 1)
    for day in range(closes):
        close = Decimal(100) if flat else Decimal(100 + day % 5)
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=start + timedelta(days=day),
                interval="1d",
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000,
                source="test",
            )
        )
    session.commit()


def _params(**extra: str) -> dict[str, str]:
    return {
        "ticker": "AAPL",
        "option_type": "call",
        "strike": "100",
        "expiry": (utcnow().date() + timedelta(days=60)).isoformat(),
        **extra,
    }


def test_a_quote_needs_twenty_closes(session: Session, client: TestClient) -> None:
    _seed(session, closes=19)
    r = client.get("/v1/options/quote", params=_params())
    assert r.status_code == 422
    assert "19 daily closes" in r.json()["detail"]


def test_a_quote_states_its_volatility_and_greeks(session: Session, client: TestClient) -> None:
    _seed(session, closes=40)
    body = client.get("/v1/options/quote", params=_params()).json()
    assert body["volatility_closes"] == 31
    assert body["volatility_method"].startswith("historical volatility")
    assert body["premium_floor_applied"] is False
    assert body["greeks"]["rho"] > 0


def test_a_far_out_of_the_money_premium_is_floored(session: Session, client: TestClient) -> None:
    _seed(session, closes=40)
    body = client.get("/v1/options/quote", params=_params(strike="1000", quantity="2")).json()
    assert body["premium_floor_applied"] is True
    assert Decimal(body["per_share"]) == MIN_PREMIUM_PER_SHARE
    assert Decimal(body["premium"]) == Decimal("2.00")  # 0.01 x 100 shares x 2


def test_implied_volatility_endpoint_round_trips_the_quote(
    session: Session, client: TestClient
) -> None:
    _seed(session, closes=40)
    quote = client.get("/v1/options/quote", params=_params()).json()
    r = client.get("/v1/options/implied-volatility", params=_params(price=quote["per_share"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reason"] is None
    assert body["implied_volatility"] == pytest.approx(body["historical_volatility"], abs=1e-4)


def test_implied_volatility_endpoint_explains_an_impossible_price(
    session: Session, client: TestClient
) -> None:
    _seed(session, closes=40)
    r = client.get("/v1/options/implied-volatility", params=_params(price="500"))
    assert r.status_code == 200
    assert r.json()["implied_volatility"] is None
    assert "bound" in r.json()["reason"]
