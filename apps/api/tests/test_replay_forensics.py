"""Pure reconstruction of replay trade episodes (SIM-07)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from stockviz.services.replay.forensics import (
    FillSnapshot,
    annotate_fill_economics,
    compute_max_drawdown_pct,
    compute_replay_forensics_from_rows,
    finish_episodes,
    reconstruct_episodes,
    sort_fills,
)

DAY1 = datetime(2024, 6, 3)
DAY2 = datetime(2024, 6, 4)
DAY3 = datetime(2024, 6, 5)
DAY4 = datetime(2024, 6, 6)


class _Bar:
    def __init__(
        self,
        ts: datetime,
        close: Decimal,
        *,
        high: Decimal | None = None,
        low: Decimal | None = None,
    ) -> None:
        self.ts = ts
        self.open = close
        self.close = close
        self.high = high if high is not None else close
        self.low = low if low is not None else close


def _fill(
    *,
    fill_id: int,
    side: str,
    quantity: str,
    price: str,
    ts: datetime,
    realized: str | None = None,
) -> FillSnapshot:
    return FillSnapshot(
        id=fill_id,
        session_id=1,
        ticker="AAPL",
        side=side,
        quantity=Decimal(quantity),
        fill_price=Decimal(price),
        realized_pnl=None if realized is None else Decimal(realized),
        evaluated_at=ts,
        created_at=ts,
        profile_name="legacy_close",
        model_version="v1",
        reference_price=Decimal(price),
        reason="market",
        assumptions=("Uses stored 1d close",),
        market_interval="1d",
        order_type="market",
        equity_after=None,
        concentration_pct=None,
    )


def test_partial_sells_stay_one_episode() -> None:
    fills = annotate_fill_economics(
        sort_fills(
            [
                _fill(fill_id=1, side="buy", quantity="2", price="100", ts=DAY1),
                _fill(
                    fill_id=2,
                    side="sell",
                    quantity="1",
                    price="120",
                    ts=DAY2,
                    realized="20",
                ),
                _fill(
                    fill_id=3,
                    side="sell",
                    quantity="1",
                    price="80",
                    ts=DAY3,
                    realized="-20",
                ),
            ]
        ),
        starting_cash=Decimal("100000"),
    )
    raw = reconstruct_episodes(fills)
    assert len(raw) == 1
    assert raw[0].buy_qty == Decimal("2")
    assert raw[0].sell_qty == Decimal("2")
    assert raw[0].qty == Decimal("0")
    assert raw[0].buy_notional / raw[0].buy_qty == Decimal("100")
    assert raw[0].realized == Decimal("0")


def test_adds_use_weighted_entry() -> None:
    fills = annotate_fill_economics(
        sort_fills(
            [
                _fill(fill_id=1, side="buy", quantity="1", price="100", ts=DAY1),
                _fill(fill_id=2, side="buy", quantity="1", price="120", ts=DAY2),
                _fill(
                    fill_id=3,
                    side="sell",
                    quantity="2",
                    price="130",
                    ts=DAY3,
                    realized="40",
                ),
            ]
        ),
        starting_cash=Decimal("100000"),
    )
    raw = reconstruct_episodes(fills)
    assert len(raw) == 1
    assert raw[0].buy_notional / raw[0].buy_qty == Decimal("110")
    episodes = finish_episodes(
        raw,
        bars=[_Bar(DAY1, Decimal("100")), _Bar(DAY2, Decimal("120")), _Bar(DAY3, Decimal("130"))],
        analysis_at=DAY3,
        mark_close=Decimal("130"),
    )
    assert episodes[0].weighted_entry_price == Decimal("110.000000")
    assert episodes[0].status == "closed"
    assert episodes[0].exit_price == Decimal("130.000000")


def test_multiple_completed_episodes_are_isolated() -> None:
    fills = annotate_fill_economics(
        sort_fills(
            [
                _fill(fill_id=1, side="buy", quantity="1", price="100", ts=DAY1),
                _fill(
                    fill_id=2,
                    side="sell",
                    quantity="1",
                    price="110",
                    ts=DAY2,
                    realized="10",
                ),
                _fill(fill_id=3, side="buy", quantity="1", price="80", ts=DAY3),
                _fill(
                    fill_id=4,
                    side="sell",
                    quantity="1",
                    price="90",
                    ts=DAY4,
                    realized="10",
                ),
            ]
        ),
        starting_cash=Decimal("100000"),
    )
    raw = reconstruct_episodes(fills)
    assert len(raw) == 2
    assert raw[0].opened_at == DAY1
    assert raw[1].opened_at == DAY3
    assert raw[0].fills[-1].id == 2
    assert raw[1].fills[0].id == 3


def test_mae_mfe_price_based_against_weighted_entry() -> None:
    fills = annotate_fill_economics(
        sort_fills(
            [
                _fill(fill_id=1, side="buy", quantity="1", price="100", ts=DAY1),
                _fill(
                    fill_id=2,
                    side="sell",
                    quantity="1",
                    price="105",
                    ts=DAY3,
                    realized="5",
                ),
            ]
        ),
        starting_cash=Decimal("100000"),
    )
    bars = [
        _Bar(DAY1, Decimal("100"), high=Decimal("103"), low=Decimal("98")),
        _Bar(DAY2, Decimal("102"), high=Decimal("110"), low=Decimal("90")),
        _Bar(DAY3, Decimal("105"), high=Decimal("106"), low=Decimal("104")),
    ]
    result = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="completed",
        start_at=DAY1,
        analysis_at=DAY3,
        starting_cash=Decimal("100000"),
        equity=Decimal("100005"),
        replay_return_pct=Decimal("0.0050"),
        fills=fills,
        bars=bars,
        mark_close=Decimal("105"),
    )
    episode = result.episodes[0]
    assert episode.mae_pct == Decimal("-10.0000")
    assert episode.mfe_pct == Decimal("10.0000")
    assert episode.mae_amount == Decimal("-10.000000")
    assert episode.mfe_amount == Decimal("10.000000")
    assert episode.holding_bars == 3
    assert episode.holding_calendar_days == 2
    assert episode.benchmark_return_pct == Decimal("5.0000")
    assert episode.return_pct == Decimal("5.0000")
    assert episode.excess_return_pct == Decimal("0.0000")


def test_future_bars_do_not_affect_mae() -> None:
    fills = annotate_fill_economics(
        sort_fills([_fill(fill_id=1, side="buy", quantity="1", price="100", ts=DAY1)]),
        starting_cash=Decimal("100000"),
    )
    bars = [
        _Bar(DAY1, Decimal("100"), high=Decimal("101"), low=Decimal("99")),
        _Bar(DAY2, Decimal("102"), high=Decimal("103"), low=Decimal("98")),
        _Bar(DAY3, Decimal("104"), high=Decimal("105"), low=Decimal("97")),
        _Bar(DAY4, Decimal("50"), high=Decimal("10000"), low=Decimal("1")),
    ]
    visible = [bar for bar in bars if bar.ts <= DAY3]
    result = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="active",
        start_at=DAY1,
        analysis_at=DAY3,
        starting_cash=Decimal("100000"),
        equity=Decimal("100004"),
        replay_return_pct=Decimal("0.0040"),
        fills=fills,
        bars=visible,
        mark_close=Decimal("104"),
    )
    episode = result.episodes[0]
    assert episode.status == "open"
    assert episode.exit_price is None
    assert result.analysis_scope == "so_far"
    assert episode.mae_pct == Decimal("-3.0000")
    assert episode.mfe_pct == Decimal("5.0000")
    assert episode.mae_amount != Decimal("-99")


def test_no_trade_session_benchmark_excess() -> None:
    bars = [
        _Bar(DAY1, Decimal("100")),
        _Bar(DAY2, Decimal("110")),
        _Bar(DAY3, Decimal("120")),
    ]
    result = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="completed",
        start_at=DAY1,
        analysis_at=DAY3,
        starting_cash=Decimal("100000"),
        equity=Decimal("100000"),
        replay_return_pct=Decimal("0"),
        fills=[],
        bars=bars,
        mark_close=Decimal("120"),
    )
    assert result.replay_return_pct == Decimal("0")
    assert result.buy_hold_return_pct == Decimal("20.0000")
    assert result.excess_return_pct == Decimal("-20.0000")
    assert result.episodes_count == 0
    assert result.max_concentration_pct == Decimal("0")
    assert result.analysis_scope == "final"


def test_replay_plus_five_vs_buy_hold_twenty() -> None:
    bars = [_Bar(DAY1, Decimal("100")), _Bar(DAY3, Decimal("120"))]
    result = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="completed",
        start_at=DAY1,
        analysis_at=DAY3,
        starting_cash=Decimal("100000"),
        equity=Decimal("105000"),
        replay_return_pct=Decimal("5.0000"),
        fills=[],
        bars=bars,
        mark_close=Decimal("120"),
    )
    assert result.buy_hold_return_pct == Decimal("20.0000")
    assert result.excess_return_pct == Decimal("-15.0000")


def test_cancelled_scope_and_completed_do_not_read_past_horizon() -> None:
    fills = annotate_fill_economics(
        sort_fills([_fill(fill_id=1, side="buy", quantity="1", price="100", ts=DAY1)]),
        starting_cash=Decimal("100000"),
    )
    cancelled = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="cancelled",
        start_at=DAY1,
        analysis_at=DAY2,
        starting_cash=Decimal("100000"),
        equity=Decimal("100010"),
        replay_return_pct=Decimal("0.0100"),
        fills=fills,
        bars=[
            _Bar(DAY1, Decimal("100"), high=Decimal("101"), low=Decimal("99")),
            _Bar(DAY2, Decimal("110"), high=Decimal("111"), low=Decimal("90")),
        ],
        mark_close=Decimal("110"),
    )
    assert cancelled.analysis_scope == "cancelled"
    assert cancelled.episodes[0].mae_pct == Decimal("-10.0000")
    assert cancelled.buy_hold_return_pct == Decimal("10.0000")

    completed = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="completed",
        start_at=DAY1,
        analysis_at=DAY2,
        starting_cash=Decimal("100000"),
        equity=Decimal("100010"),
        replay_return_pct=Decimal("0.0100"),
        fills=fills,
        bars=[
            _Bar(DAY1, Decimal("100"), high=Decimal("101"), low=Decimal("99")),
            _Bar(DAY2, Decimal("110"), high=Decimal("111"), low=Decimal("90")),
        ],
        mark_close=Decimal("110"),
    )
    assert completed.analysis_scope == "final"
    assert completed.episodes[0].mfe_pct == Decimal("11.0000")


def test_concentration_is_notional_over_equity() -> None:
    fills = annotate_fill_economics(
        sort_fills([_fill(fill_id=1, side="buy", quantity="10", price="100", ts=DAY1)]),
        starting_cash=Decimal("10000"),
    )
    assert fills[0].concentration_pct == Decimal("10.0000")
    result = compute_replay_forensics_from_rows(
        ticker="AAPL",
        status="active",
        start_at=DAY1,
        analysis_at=DAY1,
        starting_cash=Decimal("10000"),
        equity=Decimal("10000"),
        replay_return_pct=Decimal("0"),
        fills=fills,
        bars=[_Bar(DAY1, Decimal("100"))],
        mark_close=Decimal("100"),
    )
    assert result.max_concentration_pct == Decimal("10.0000")
    assert result.episodes[0].max_position_pct == Decimal("10.0000")


def test_max_drawdown_from_equity_curve() -> None:
    navs = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")]
    dd = compute_max_drawdown_pct(navs)
    assert dd == Decimal("-25.0000")
