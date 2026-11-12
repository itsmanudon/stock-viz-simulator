"""Phase 5.1: forensics measures from the fill, against the ledger's cost (SR-2, SR-6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from stockviz.services.replay.forensics import (
    FillSnapshot,
    finish_episodes,
    reconstruct_episodes,
)
from stockviz.services.simulation import OrderSide, SimLedger


@dataclass
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def _day(n: int) -> datetime:
    return datetime(2024, 6, n)


def _bar(n: int, low: str, high: str, close: str) -> Bar:
    return Bar(_day(n), Decimal(close), Decimal(high), Decimal(low), Decimal(close))


def _fill(n: int, side: str, qty: str, price: str, fid: int) -> FillSnapshot:
    return FillSnapshot(
        id=fid,
        session_id=1,
        ticker="AAPL",
        side=side,
        quantity=Decimal(qty),
        fill_price=Decimal(price),
        realized_pnl=None,
        evaluated_at=_day(n),
        created_at=_day(n),
        profile_name="legacy_close",
        model_version="1",
        reference_price=Decimal(price),
        reason="filled",
        assumptions=(),
        market_interval="1d",
        order_type="market",
        equity_after=None,
        concentration_pct=None,
    )


def test_mae_mfe_start_at_the_fill_and_include_the_exit_bar() -> None:
    # Bought at day 3's close (100); the day's range 80-130 happened before it.
    # Day 4 (held all day) ranges 95-105. Sold at day 5's close; day 5 held all
    # day and ranged 90-120 before the sale.
    bars = [_bar(3, "80", "130", "100"), _bar(4, "95", "105", "100"), _bar(5, "90", "120", "110")]
    fills = [_fill(3, "buy", "10", "100", 1), _fill(5, "sell", "10", "110", 2)]
    (episode,) = finish_episodes(
        reconstruct_episodes(fills), bars=bars, analysis_at=_day(5), mark_close=Decimal(110)
    )
    assert episode.mae_amount == Decimal("-10.00")  # day 5's low, not day 3's 80
    assert episode.mfe_amount == Decimal("20.00")  # day 5's high counts; day 3's 130 does not


def test_entry_follows_the_ledger_after_a_partial_sell_and_an_add() -> None:
    fills = [
        _fill(3, "buy", "10", "100", 1),
        _fill(4, "sell", "5", "120", 2),
        _fill(5, "buy", "5", "140", 3),
    ]
    bars = [_bar(n, "90", "150", p) for n, p in ((3, "100"), (4, "120"), (5, "140"))]
    (episode,) = finish_episodes(
        reconstruct_episodes(fills), bars=bars, analysis_at=_day(5), mark_close=Decimal(140)
    )
    ledger = SimLedger(cash=Decimal(10_000))
    ledger.apply(OrderSide.BUY, "AAPL", Decimal(10), Decimal(100))
    ledger.apply(OrderSide.SELL, "AAPL", Decimal(5), Decimal(120))
    ledger.apply(OrderSide.BUY, "AAPL", Decimal(5), Decimal(140))

    held = ledger.positions["AAPL"]
    assert held.avg_cost == Decimal("120")  # (100 x 5 + 140 x 5) / 10
    assert episode.weighted_entry_price == Decimal("120.00")  # was 116.67 (all buys / all bought)
    assert episode.unrealized_pnl == Decimal("200.00")  # (140 - 120) x 10
