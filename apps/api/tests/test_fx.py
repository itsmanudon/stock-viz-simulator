"""Multi-currency tests: FX ingest, conversion, trades, portfolio valuation.

The ingest path uses a stubbed yfinance fetcher (pandas-shaped DataFrame) so
no network is touched. Trading and valuation tests use the SQLite session
fixture from conftest.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from sqlmodel import Session

from stockviz.models import FxRate, PriceBar, Symbol, TradeSide, User
from stockviz.services.ingest.fx import fetch_yfinance_fx, ingest_fx
from stockviz.services.trading import (
    NoFxRateError,
    compute_portfolio,
    ensure_default_portfolio,
    execute_trade,
)
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.fx import latest_rate


def _stub_yf(rows: list[tuple[date, str]]) -> Any:
    """Return a callable mimicking yfinance's history(...) DataFrame.

    Each row is (date, close-as-string). The fetcher only reads the index
    (datetime) and the ``Close`` column.
    """

    def _fn(_yahoo_ticker: str, _start: date | None) -> Any:
        if not rows:
            return pd.DataFrame()
        idx = [datetime(d.year, d.month, d.day) for d, _ in rows]
        return pd.DataFrame({"Close": [c for _, c in rows]}, index=idx)

    return _fn


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_fetch_yfinance_fx_shapes_rows() -> None:
    fetcher = _stub_yf(
        [
            (date(2026, 5, 15), "1.0850"),
            (date(2026, 5, 16), "1.0900"),
        ]
    )
    out = fetch_yfinance_fx("EUR", history_fn=fetcher)
    assert [r.date for r in out] == [date(2026, 5, 15), date(2026, 5, 16)]
    assert out[0].usd_rate == Decimal("1.0850")
    assert out[0].currency == "EUR"


def test_fetch_usd_returns_empty() -> None:
    out = fetch_yfinance_fx("USD")
    assert out == []


def test_ingest_fx_usd_short_circuits(session: Session) -> None:
    """The orchestrator skips USD (no rate to fetch, no row to write)."""
    assert ingest_fx(session, "USD") == 0


# NB: the Postgres-specific ON CONFLICT path in ``upsert_fx_rates`` mirrors
# ``upsert_bars`` in services/ingest/prices.py and is covered by the same
# smoke-test approach (run against the docker-compose Postgres in CI, not
# SQLite). We rely on the fetch -> record shape being correct, which is
# exercised above.


# ---------------------------------------------------------------------------
# Lookup / conversion
# ---------------------------------------------------------------------------


def test_latest_rate_usd_short_circuits(session: Session) -> None:
    assert latest_rate(session, "USD") == Decimal(1)


def test_latest_rate_forward_fills(session: Session) -> None:
    session.add(FxRate(currency="EUR", date=date(2026, 5, 14), usd_rate=Decimal("1.08")))
    session.add(FxRate(currency="EUR", date=date(2026, 5, 15), usd_rate=Decimal("1.09")))
    session.commit()
    # Sunday: most recent on-or-before is Friday's 1.09.
    assert latest_rate(session, "EUR", on_or_before=date(2026, 5, 17)) == Decimal("1.09")
    # Earlier date pulls the earlier row.
    assert latest_rate(session, "EUR", on_or_before=date(2026, 5, 14)) == Decimal("1.08")


def test_latest_rate_missing_raises(session: Session) -> None:
    with pytest.raises(LookupError):
        latest_rate(session, "EUR", on_or_before=date(2026, 5, 16))


def test_convert_eur_to_jpy_via_usd(session: Session) -> None:
    # 1 EUR = 1.10 USD; 1 JPY = 0.0067 USD ⇒ 1 EUR ≈ 164.18 JPY
    session.add(FxRate(currency="EUR", date=date(2026, 5, 16), usd_rate=Decimal("1.10")))
    session.add(FxRate(currency="JPY", date=date(2026, 5, 16), usd_rate=Decimal("0.0067")))
    session.commit()
    out = fx_convert(
        session,
        Decimal("100"),
        from_currency="EUR",
        to_currency="JPY",
        on_or_before=date(2026, 5, 16),
    )
    # 100 EUR * 1.10 = 110 USD; 110 / 0.0067 ≈ 16,417.91 JPY
    assert out > Decimal("16000") and out < Decimal("17000")


def test_convert_same_currency_is_identity(session: Session) -> None:
    assert fx_convert(session, Decimal("42"), from_currency="USD", to_currency="USD") == Decimal(
        "42"
    )


# ---------------------------------------------------------------------------
# Trading + valuation
# ---------------------------------------------------------------------------


def _seed_eur_symbol(session: Session, *, price: str = "120", fx: str = "1.10") -> None:
    """Set up SAP.DE (EUR) with a single 1d bar and today's FX rate."""
    session.add(Symbol(ticker="SAP.DE", name="SAP SE", currency="EUR"))
    session.commit()
    session.add(
        PriceBar(
            ticker="SAP.DE",
            ts=datetime(2026, 5, 16),
            interval="1d",
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            volume=1_000_000,
            source="test",
        )
    )
    from stockviz._time import utcnow

    today = utcnow().date()
    session.add(FxRate(currency="EUR", date=today, usd_rate=Decimal(fx)))
    session.commit()


def _make_user(session: Session, display_currency: str = "USD") -> int:
    user = User(email="ccy@stockviz.dev", name="Multi", display_currency=display_currency)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_buy_non_usd_symbol_debits_usd_at_fx_rate(session: Session) -> None:
    _seed_eur_symbol(session, price="120", fx="1.10")  # 1 EUR = $1.10
    user_id = _make_user(session)

    # Buy 10 SAP.DE @ €120 = €1,200 native = $1,320 USD debit
    result = execute_trade(
        session, user_id=user_id, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(10)
    )
    assert result.currency == "EUR"
    assert result.fx_rate == Decimal("1.10")
    assert result.native_cost == Decimal("1200.000000")
    assert result.usd_cost == Decimal("1320.000000")

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == Decimal("100000.000000") - Decimal("1320.000000")


def test_buy_without_fx_rate_raises(session: Session) -> None:
    # SAP.DE seeded as EUR but no fx_rates row -> NoFxRateError.
    session.add(Symbol(ticker="SAP.DE", name="SAP SE", currency="EUR"))
    session.commit()
    session.add(
        PriceBar(
            ticker="SAP.DE",
            ts=datetime(2026, 5, 16),
            interval="1d",
            open=Decimal("120"),
            high=Decimal("120"),
            low=Decimal("120"),
            close=Decimal("120"),
            volume=1,
            source="test",
        )
    )
    session.commit()

    user_id = _make_user(session)
    with pytest.raises(NoFxRateError):
        execute_trade(
            session, user_id=user_id, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(1)
        )


def test_portfolio_converts_to_display_currency(session: Session) -> None:
    _seed_eur_symbol(session, price="120", fx="1.10")
    user_id = _make_user(session, display_currency="EUR")
    execute_trade(
        session, user_id=user_id, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(10)
    )

    portfolio = ensure_default_portfolio(session, user_id)
    snap = compute_portfolio(session, portfolio, display_currency="EUR")
    assert snap.display_currency == "EUR"
    assert len(snap.positions) == 1
    pos = snap.positions[0]
    # Native unchanged: €120 * 10 = €1,200.
    assert pos.market_value_native == Decimal("1200")
    # Display: matches native because EUR == display_currency.
    assert pos.market_value == Decimal("1200")
    # Cash: $98,680 / 1.10 ≈ €89,709.09
    assert snap.cash_balance < Decimal("90000")
    assert snap.cash_balance > Decimal("89000")


def test_portfolio_native_and_display_diverge_for_usd_display(session: Session) -> None:
    _seed_eur_symbol(session, price="120", fx="1.10")
    user_id = _make_user(session, display_currency="USD")
    execute_trade(
        session, user_id=user_id, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(10)
    )

    portfolio = ensure_default_portfolio(session, user_id)
    snap = compute_portfolio(session, portfolio, display_currency="USD")
    pos = snap.positions[0]
    assert pos.market_value_native == Decimal("1200")  # €1200 native
    assert pos.market_value == Decimal("1320")  # $1320 display
    # Cash USD: 100k - 1320 = 98,680
    assert snap.cash_balance == Decimal("98680.000000")
    # Total in USD: 98,680 + 1,320 = 100,000 (round trip)
    assert snap.total_value == Decimal("100000.000000")
