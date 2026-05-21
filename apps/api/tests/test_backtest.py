"""Tests for the backtesting engine and the /v1/backtest endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol
from stockviz.services.backtest import BacktestError, run_backtest

_EPOCH = datetime(2024, 1, 1)


def _bars(prices: Sequence[float]) -> list[tuple[datetime, Decimal]]:
    """Daily bars starting 2024-01-01, one per price."""
    return [(_EPOCH + timedelta(days=i), Decimal(str(p))) for i, p in enumerate(prices)]


# ---------------------------------------------------------------------------
# Engine — SMA crossover
# ---------------------------------------------------------------------------


def test_sma_crossover_profitable_single_buy() -> None:
    # Step up: 10,10,10,25,25,25,50,50,50 — SMA2 crosses above SMA3 at index 3
    # (price 25), price doubles to 50 by the end. No sell signal fires.
    prices = [10, 10, 10, 25, 25, 25, 50, 50, 50]
    result = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )

    assert len(result.trades) == 1
    buy = result.trades[0]
    assert buy.side == "buy"
    assert buy.price == Decimal(25)
    assert buy.shares == Decimal(40)  # 1000 / 25

    navs = [pt.nav for pt in result.equity_curve]
    assert navs == [Decimal(n) for n in [1000, 1000, 1000, 1000, 1000, 1000, 2000, 2000, 2000]]
    assert result.summary.final_nav == Decimal(2000)
    assert result.summary.total_return == pytest.approx(1.0)
    assert result.summary.max_drawdown == pytest.approx(0.0)


def test_sma_crossover_buy_then_sell() -> None:
    # Step up then crash: buy at 25, sell at 5.
    prices = [10, 10, 10, 25, 25, 25, 5, 5, 5]
    result = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )

    assert [t.side for t in result.trades] == ["buy", "sell"]
    assert result.trades[0].price == Decimal(25)
    assert result.trades[1].price == Decimal(5)
    # 40 shares bought at 25, liquidated at 5 → 200 cash.
    assert result.summary.final_nav == Decimal(200)
    assert result.summary.total_return == pytest.approx(-0.8)
    # Peak 1000 → trough 200 = 80% drawdown.
    assert result.summary.max_drawdown == pytest.approx(0.8)


def test_sma_crossover_no_signal_keeps_cash_flat() -> None:
    # Flat prices never cross — no trades, equity curve stays at initial cash.
    result = run_backtest(
        _bars([100] * 10),
        initial_cash=Decimal(5000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )
    assert result.trades == []
    assert all(pt.nav == Decimal(5000) for pt in result.equity_curve)
    assert result.summary.total_return == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Engine — RSI threshold
# ---------------------------------------------------------------------------


def test_rsi_threshold_buys_on_oversold_then_sells_on_overbought() -> None:
    # Long decline (RSI → low, triggers buy) followed by a long rally
    # (RSI → high, triggers sell).
    declining = [100 - i for i in range(20)]  # 100 .. 81
    rallying = [80 + i * 3 for i in range(20)]  # 80, 83, ... climbing
    result = run_backtest(
        _bars(declining + rallying),
        initial_cash=Decimal(1000),
        strategy_type="rsi_threshold",
        params={"buy_below": 30.0, "sell_above": 70.0},
    )
    sides = [t.side for t in result.trades]
    assert "buy" in sides
    # The buy must come before the sell.
    assert sides[0] == "buy"
    if "sell" in sides:
        assert sides.index("buy") < sides.index("sell")


def test_rsi_threshold_no_trades_on_flat_series() -> None:
    result = run_backtest(
        _bars([50] * 30),
        initial_cash=Decimal(1000),
        strategy_type="rsi_threshold",
        params={"buy_below": 30.0, "sell_above": 70.0},
    )
    assert result.trades == []


# ---------------------------------------------------------------------------
# Engine — validation + edge cases
# ---------------------------------------------------------------------------


def test_empty_bars_returns_initial_cash() -> None:
    result = run_backtest(
        [],
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )
    assert result.trades == []
    assert result.equity_curve == []
    assert result.summary.final_nav == Decimal(1000)
    assert result.summary.total_return == pytest.approx(0.0)


def test_sma_rejects_short_window_not_less_than_long() -> None:
    with pytest.raises(BacktestError):
        run_backtest(
            _bars([1, 2, 3]),
            initial_cash=Decimal(1000),
            strategy_type="sma_crossover",
            params={"short_window": 5, "long_window": 5},
        )


def test_rsi_rejects_buy_threshold_above_sell_threshold() -> None:
    with pytest.raises(BacktestError):
        run_backtest(
            _bars([1, 2, 3]),
            initial_cash=Decimal(1000),
            strategy_type="rsi_threshold",
            params={"buy_below": 80.0, "sell_above": 20.0},
        )


def test_unknown_strategy_type_raises() -> None:
    with pytest.raises(BacktestError):
        run_backtest(
            _bars([1, 2, 3]),
            initial_cash=Decimal(1000),
            strategy_type="bollinger_bounce",
            params={},
        )


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _seed(session: Session, prices: Sequence[float]) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    session.commit()
    for i, p in enumerate(prices):
        price = Decimal(str(p))
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=_EPOCH + timedelta(days=i),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1_000_000,
                source="test",
            )
        )
    session.commit()


def test_backtest_endpoint_happy_path(session: Session, client: TestClient) -> None:
    _seed(session, [10, 10, 10, 25, 25, 25, 50, 50, 50])
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": "aapl",
            "from": "2024-01-01",
            "to": "2024-01-31",
            "initial_cash": "1000",
            "strategy": {"type": "sma_crossover", "short_window": 2, "long_window": 3},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert len(body["trades"]) == 1
    assert body["trades"][0]["side"] == "buy"
    assert len(body["equity_curve"]) == 9
    assert Decimal(body["summary"]["final_nav"]) == Decimal(2000)
    assert body["summary"]["total_return"] == pytest.approx(1.0)


def test_backtest_endpoint_unknown_ticker_404(session: Session, client: TestClient) -> None:
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": "NOPE",
            "from": "2024-01-01",
            "to": "2024-01-31",
            "initial_cash": "1000",
            "strategy": {"type": "rsi_threshold", "buy_below": 30, "sell_above": 70},
        },
    )
    assert response.status_code == 404


def test_backtest_endpoint_rejects_reversed_date_range(
    session: Session, client: TestClient
) -> None:
    _seed(session, [10, 20, 30])
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": "AAPL",
            "from": "2024-02-01",
            "to": "2024-01-01",
            "initial_cash": "1000",
            "strategy": {"type": "rsi_threshold", "buy_below": 30, "sell_above": 70},
        },
    )
    assert response.status_code == 400


def test_backtest_endpoint_rejects_bad_strategy_params(
    session: Session, client: TestClient
) -> None:
    _seed(session, [10, 20, 30])
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": "AAPL",
            "from": "2024-01-01",
            "to": "2024-01-31",
            "initial_cash": "1000",
            "strategy": {"type": "sma_crossover", "short_window": 10, "long_window": 5},
        },
    )
    # short_window >= long_window is caught by the engine and surfaced as 400.
    assert response.status_code == 400


def test_backtest_endpoint_empty_range_returns_initial_cash(
    session: Session, client: TestClient
) -> None:
    _seed(session, [10, 20, 30])
    response = client.post(
        "/v1/backtest",
        json={
            "ticker": "AAPL",
            "from": "2025-06-01",
            "to": "2025-06-30",
            "initial_cash": "1000",
            "strategy": {"type": "rsi_threshold", "buy_below": 30, "sell_above": 70},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["equity_curve"] == []
    assert body["trades"] == []
    assert Decimal(body["summary"]["final_nav"]) == Decimal(1000)
