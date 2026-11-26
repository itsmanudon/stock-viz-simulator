"""A4's done-when: a live fill, a replay fill and a backtest fill for the same
bar agree (``docs/a4-design-note.md`` section 3, "Kernel equality").

For one fixture bar and a set of orders (market, limit and stop; buy and
sell; one limit that does not trigger) each path fills through its own
production code:

- **live**: ``execute_trade`` (market) and ``create_pending_order`` +
  ``settle_pending_orders`` (limit, stop), so ``apply_fill`` books it;
- **replay**: ``create_replay_session`` + ``submit_replay_order``;
- **backtest**: ``services/backtest/fills.book``, the function every DSL
  backtest fill goes through.

Compared: fill or no fill, fill price, quantity, the cash change and (USD)
the realised P&L. A4.2: live fills pay the ticker's default schedule
(Indian symbols: their venue's delivery schedule, version in force on the
fill's venue date; US: none). So under the live default the backtest's cash
change and fees equal live's to the cent; under any other schedule the
backtest's cash change equals live's before its fees, less exactly that
schedule's fees on the same fill and date. A4.6: replay trades in the
symbol's currency and pays the same default (``auto``) on the bar's venue
date, so the INR replay path is compared like live, fees included. A replay
limit or stop order rests: it is placed on DAY1 and judged on DAY2, as live
settles a pending order on DAY2's bar.

What a path does not support is a skip with its reason (never silent):
live is pinned to ``legacy_close``; ``next_open`` exists only in backtests
(it is compared against the kernel's own rule in
:func:`test_next_open_backtest_path`). A6.9: ``intrabar_ohlc`` is a replay and
backtest profile, so replay (a session created under it) is compared with
the backtest path on every order, and live is skipped; a bracket's exit with
the stop and the target both inside the bar is compared too
(:func:`test_bracket_exit_replay_equals_backtest`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz.models import (
    FxRate,
    Portfolio,
    PriceBar,
    ReplayFill,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.order import OrderType
from stockviz.services.backtest.fills import book
from stockviz.services.fee_view import default_schedule_name, fee_date
from stockviz.services.replay import (
    advance_replay_session,
    create_replay_session,
    submit_replay_order,
)
from stockviz.services.simulation import (
    INTRABAR_OHLC,
    INTRABAR_UNKNOWN_LABEL,
    LEGACY_CLOSE,
    NEXT_OPEN,
    ExecutionProfile,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimLedger,
    SimulationOrderType,
    evaluate_oco_exit,
    evaluate_order,
    get_execution_profile,
    get_fee_schedule,
)
from stockviz.services.trading import (
    create_pending_order,
    ensure_default_portfolio,
    execute_trade,
    settle_pending_orders,
)
from stockviz.services.trading.execute import apply_fill

DAY1 = datetime(2025, 4, 9)
DAY2 = datetime(2025, 4, 10)
OPEN, HIGH, LOW, CLOSE = Decimal("101.25"), Decimal("104.5"), Decimal("97.125"), Decimal("100.37")
HELD_AT = Decimal("90")
HELD = Decimal(10)
QTY = Decimal(7)
MICROS = Decimal("0.000001")
TICKERS = {"USD": "AAPL", "INR": "TCS.NS"}
FEES = {
    "USD": ("none", "us_equity_2026", "us_equity"),
    "INR": ("none", "in_delivery_nse_2026", "in_equity_delivery_nse", "in_delivery_bse_2026"),
}


@dataclass(frozen=True)
class Order:
    name: str
    side: OrderSide
    kind: SimulationOrderType
    limit: Decimal | None = None


ORDERS = (
    Order("market_buy", OrderSide.BUY, SimulationOrderType.MARKET),
    Order("market_sell", OrderSide.SELL, SimulationOrderType.MARKET),
    Order("limit_buy", OrderSide.BUY, SimulationOrderType.LIMIT, Decimal("100.5")),
    # Below the bar's low (97.125) and its close: no fill under either profile.
    Order("limit_buy_not_triggered", OrderSide.BUY, SimulationOrderType.LIMIT, Decimal("97")),
    Order("limit_sell", OrderSide.SELL, SimulationOrderType.LIMIT, Decimal("99.5")),
    Order("stop_sell", OrderSide.SELL, SimulationOrderType.STOP_LOSS, Decimal("100.5")),
    # A6.9: above the close, below the high: only intrabar_ohlc fills it.
    Order("target_sell", OrderSide.SELL, SimulationOrderType.TAKE_PROFIT, Decimal("104")),
)
NOT_FILLED = {
    "legacy_close": {"limit_buy_not_triggered", "target_sell"},
    "intrabar_ohlc": {"limit_buy_not_triggered"},
}


@dataclass(frozen=True)
class Fill:
    price: Decimal
    quantity: Decimal
    cash_change: Decimal  # in the symbol's currency, fees included
    realized: Decimal | None
    fees: Decimal = Decimal(0)
    fee_on: date | None = None
    """The date the path priced its fees on (None: it books none)."""


def _seed(session: Session, currency: str) -> str:
    ticker = TICKERS[currency]
    session.add(Symbol(ticker=ticker, name=ticker, currency=currency))
    session.commit()
    for ts, (o, h, lo, c) in ((DAY1, (HELD_AT,) * 4), (DAY2, (OPEN, HIGH, LOW, CLOSE))):
        session.add(PriceBar(ticker=ticker, ts=ts, interval="1d", open=o, high=h, low=lo,
                             close=c, volume=1000, source="test"))  # fmt: skip
    if currency != "USD":
        # Market fills check the rate's age against today; settlement against DAY2.
        for day in {DAY1.date(), DAY2.date(), datetime.now(UTC).date()}:
            session.add(FxRate(currency=currency, date=day, usd_rate=Decimal("0.012")))
    session.commit()
    return ticker


def _user(session: Session) -> int:
    row = User(email="three-way@stockviz.dev", name="T")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def live_fill(session: Session, currency: str, order: Order) -> Fill | None:
    ticker = _seed(session, currency)
    uid = _user(session)
    portfolio = ensure_default_portfolio(session, uid)
    if order.side is OrderSide.SELL:
        fx = Decimal(1) if currency == "USD" else Decimal("0.012")
        apply_fill(session, portfolio=portfolio, ticker=ticker, side=TradeSide.BUY,
                   quantity=HELD, price=HELD_AT, currency=currency, fx_rate=fx)  # fmt: skip
        session.commit()
    before = session.exec(select(Trade.id)).all()
    cash_before = session.get(Portfolio, portfolio.id).cash_balance  # type: ignore[union-attr]
    side = TradeSide.BUY if order.side is OrderSide.BUY else TradeSide.SELL
    if order.kind is SimulationOrderType.MARKET:
        execute_trade(session, user_id=uid, ticker=ticker, side=side, quantity=QTY)
    else:
        assert order.limit is not None
        kind = OrderType(order.kind.value)
        create_pending_order(session, user_id=uid, ticker=ticker, side=side, order_type=kind,
                             quantity=QTY, limit_price=order.limit)  # fmt: skip
        settle_pending_orders(session, session_date=DAY2.date())
    trade = session.exec(select(Trade).where(col(Trade.id).not_in(before))).first()
    if trade is None:
        return None
    native = (trade.price * trade.quantity).quantize(MICROS)
    fees = trade.fees if trade.fees is not None else Decimal(0)
    change = -native - fees if trade.side == TradeSide.BUY else native - fees
    if currency == "USD":
        session.expire_all()
        after = session.get(Portfolio, portfolio.id).cash_balance  # type: ignore[union-attr]
        assert after - cash_before == change
    else:
        # The rupee leg: a buy converts native + fees from USD cash; a sell
        # credits native - fees to the INR balance.
        from stockviz.models import CashBalance

        session.expire_all()
        row = session.exec(select(CashBalance).where(CashBalance.currency == "INR")).first()
        held = row.amount if row is not None else None
        if trade.side == TradeSide.SELL:
            assert held == native - fees
    realized = trade.realized_pnl if currency == "USD" else None
    assert trade.fee_schedule == default_schedule_name(ticker)
    return Fill(trade.price, trade.quantity, change, realized, fees, fee_date(ticker, trade.ts))


def replay_fill(
    session: Session, currency: str, order: Order, profile: str = "legacy_close"
) -> Fill | None:
    ticker = _seed(session, currency)
    uid = _user(session)
    # A4.6: an Indian session must end 30 days before today; DAY2 is long past.
    replay = create_replay_session(session, user_id=uid, ticker=ticker, start_at=DAY1,
                                   end_at=DAY2, profile=profile)  # fmt: skip
    assert replay.profile_name == profile
    assert replay.currency == currency
    assert replay.fee_schedule == default_schedule_name(ticker)
    if order.side is OrderSide.SELL:
        submit_replay_order(session, replay=replay, side=OrderSide.BUY,
                            order_type=SimulationOrderType.MARKET, quantity=HELD)  # fmt: skip
    if order.kind is SimulationOrderType.MARKET:
        replay = advance_replay_session(session, replay=replay)
        before = replay.cash_balance
        result = submit_replay_order(session, replay=replay, side=order.side,
                                     order_type=order.kind, quantity=QTY)  # fmt: skip
        fill = result.fill
        after = result.replay.cash_balance
    else:
        # Resting: placed on DAY1, judged by the kernel when the clock reaches DAY2.
        placed = submit_replay_order(session, replay=replay, side=order.side,
                                     order_type=order.kind, quantity=QTY,
                                     limit_price=order.limit)  # fmt: skip
        assert placed.fill is None and placed.order is not None
        before = placed.replay.cash_balance
        replay = advance_replay_session(session, replay=placed.replay)
        after = replay.cash_balance
        fill = session.exec(
            select(ReplayFill).where(ReplayFill.order_id == placed.order.id)
        ).first()
    if fill is None:
        return None
    assert fill.evaluated_at == DAY2
    return Fill(fill.fill_price, fill.quantity, after - before,
                fill.realized_pnl, fill.fees, DAY2.date())  # fmt: skip


def backtest_fill(
    currency: str,
    order: Order,
    profile: ExecutionProfile,
    fee_schedule: str,
    on: date | None = None,
) -> tuple[Fill | None, Decimal]:
    """The backtest path's fill and the fees it charged."""
    ticker = TICKERS[currency]
    ledger = SimLedger(cash=Decimal(100_000))
    if order.side is OrderSide.SELL:
        ledger.apply(OrderSide.BUY, ticker, HELD, HELD_AT)
    intent = OrderIntent(ticker=ticker, side=order.side, order_type=order.kind, quantity=QTY,
                         submitted_at=DAY1.replace(tzinfo=UTC), limit_price=order.limit)  # fmt: skip
    bar = MarketSnapshot(ticker=ticker, observed_at=DAY2.replace(tzinfo=UTC), interval="1d",
                         open=OPEN, high=HIGH, low=LOW, close=CLOSE, volume=Decimal(1000))  # fmt: skip
    booked = book(ledger, intent, bar, profile, schedule=get_fee_schedule(fee_schedule), on=on)
    if booked is None:
        return None, Decimal(0)
    return (
        Fill(booked.price, booked.fill.quantity, booked.cash_change, booked.fill.realized_pnl),
        booked.fees.total,
    )


def _agree(
    path: Fill | None,
    currency: str,
    order: Order,
    fee_schedule: str,
    profile: ExecutionProfile = LEGACY_CLOSE,
) -> None:
    on = path.fee_on if path is not None else None
    backtest, fees = backtest_fill(currency, order, profile, fee_schedule, on=on)
    assert (path is None) == (backtest is None), (order.name, fee_schedule)
    if path is None or backtest is None:
        return
    assert (backtest.price, backtest.quantity) == (path.price, path.quantity)
    expected_fees = (
        get_fee_schedule(fee_schedule)
        .fees(order.side, path.quantity, path.price, on=on or DAY2.date())
        .total
    )
    assert fees == expected_fees.quantize(MICROS)
    gross = path.cash_change + path.fees  # the path's cash change before its own fees
    assert backtest.cash_change == gross - fees, (order.name, fee_schedule)
    if path.fee_on is not None and get_fee_schedule(fee_schedule) is get_fee_schedule(
        default_schedule_name(TICKERS[currency])
    ):
        # The live default schedule: fees and cash agree to the cent.
        assert fees == path.fees and backtest.cash_change == path.cash_change
        assert (fees > 0) == (currency == "INR")
    if path.realized is not None:
        assert backtest.realized == path.realized


SKIPS: dict[tuple[str, ...], str] = {
    (
        "live",
        "next_open",
    ): "live paper trading is pinned to legacy_close (LIVE_PAPER_EXECUTION_PROFILE)",
    ("replay", "next_open"): "next_open is a backtest profile, not a replay one",
    (
        "live",
        "intrabar_ohlc",
    ): "live paper trading is pinned to legacy_close; intrabar_ohlc is replay and backtests",
}


@pytest.mark.parametrize("currency", ["USD", "INR"])
@pytest.mark.parametrize("profile", ["legacy_close", "next_open", "intrabar_ohlc"])
@pytest.mark.parametrize("path", ["live", "replay"])
def test_path_agrees_with_backtest(engine, path: str, profile: str, currency: str) -> None:
    """Every order in ``ORDERS`` under every fee schedule of the currency."""
    reason = SKIPS.get((path, profile)) or SKIPS.get((path, profile, currency))
    if reason:
        pytest.skip(reason)
    from sqlmodel import SQLModel

    for order in ORDERS:
        # A fresh database per order: each path seeds its own fixture.
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            fill = (
                live_fill(session, currency, order)
                if path == "live"
                else replay_fill(session, currency, order, profile)
            )
        assert (fill is None) == (order.name in NOT_FILLED[profile]), order.name
        for fee_schedule in FEES[currency]:
            _agree(fill, currency, order, fee_schedule, get_execution_profile(profile, "v1"))


def test_three_way_market_buy_headline(engine) -> None:
    """The done-when in one place: the same bar, a market buy, all three paths."""
    with Session(engine) as session:
        live = live_fill(session, "USD", ORDERS[0])
    from sqlmodel import SQLModel

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        replay = replay_fill(session, "USD", ORDERS[0])
    backtest, fees = backtest_fill("USD", ORDERS[0], LEGACY_CLOSE, "none")
    assert live is not None and replay is not None and backtest is not None and fees == 0
    assert (live.price, live.quantity, live.cash_change, live.fees) == (
        replay.price, replay.quantity, replay.cash_change, replay.fees
    ) == (backtest.price, backtest.quantity, backtest.cash_change, backtest.fees)  # fmt: skip
    assert live.price == CLOSE and live.cash_change == -(CLOSE * QTY)


def test_three_way_inr_default_fees(engine) -> None:
    """A4.2: an Indian market buy and sell pay the NSE delivery schedule live,
    and the backtest under the same schedule and date books the same fees and
    the same cash change, to the cent."""
    from sqlmodel import SQLModel

    for order in (ORDERS[0], ORDERS[1]):
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            live = live_fill(session, "INR", order)
        assert live is not None and live.fees > 0 and live.fee_on is not None
        backtest, fees = backtest_fill(
            "INR", order, LEGACY_CLOSE, default_schedule_name("TCS.NS"), on=live.fee_on
        )
        assert backtest is not None
        assert (backtest.cash_change, fees) == (live.cash_change, live.fees)


def test_three_way_inr_replay_equals_live(engine) -> None:
    """A4.6: an Indian market buy and sell in replay pay the same NSE delivery
    fees as live on the same date, and the backtest books the same cash
    change, to the cent."""
    from sqlmodel import SQLModel

    for order in (ORDERS[0], ORDERS[1], ORDERS[4]):
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            replay = replay_fill(session, "INR", order)
        assert replay is not None and replay.fees > 0 and replay.fee_on == DAY2.date()
        backtest, fees = backtest_fill(
            "INR", order, LEGACY_CLOSE, default_schedule_name("TCS.NS"), on=replay.fee_on
        )
        assert backtest is not None
        assert (backtest.cash_change, fees, backtest.price) == (
            replay.cash_change,
            replay.fees,
            replay.price,
        )


@pytest.mark.parametrize("order", ORDERS, ids=[o.name for o in ORDERS])
def test_next_open_backtest_path(order: Order) -> None:
    """``next_open`` is backtest-only: its fill must be the kernel's decision
    (the open for market orders; limit and stop orders are ineligible)."""
    fill, _fees = backtest_fill("USD", order, NEXT_OPEN, "none")
    decision = evaluate_order(
        OrderIntent(ticker="AAPL", side=order.side, order_type=order.kind, quantity=QTY,
                    submitted_at=DAY1.replace(tzinfo=UTC), limit_price=order.limit),
        MarketSnapshot(ticker="AAPL", observed_at=DAY2.replace(tzinfo=UTC), interval="1d",
                       open=OPEN, high=HIGH, low=LOW, close=CLOSE, volume=Decimal(1000)),
        NEXT_OPEN,
    )  # fmt: skip
    if order.kind is SimulationOrderType.MARKET:
        assert decision.status is FillStatus.FILLED and fill is not None
        assert fill.price == decision.fill_price == OPEN
    else:
        assert decision.status is FillStatus.INELIGIBLE and fill is None


def test_intrabar_fills_differ_from_the_close() -> None:
    """The profile is not a relabelled close: on the fixture bar the range
    rule fills at the level or the open, never at the close."""
    expected = {
        "limit_buy": Decimal("100.5"),
        "limit_sell": OPEN,  # the bar opened above the sell limit
        "stop_sell": Decimal("100.5"),
        "target_sell": Decimal("104"),
    }
    for order in ORDERS:
        fill, _ = backtest_fill("USD", order, INTRABAR_OHLC, "none")
        if order.name in expected:
            assert fill is not None and fill.price == expected[order.name], order.name


def test_bracket_exit_replay_equals_backtest(engine) -> None:
    """A bracket bought at DAY1's close (100) with its stop (98) and target
    (104) both inside DAY2's range, no minutes stored: replay fills the stop,
    labelled, at the price and cash the kernel's ``evaluate_oco_exit`` and
    ``SimLedger`` give the backtest."""
    from sqlmodel import SQLModel

    from stockviz.services.replay import list_replay_orders
    from stockviz.services.replay.session import submit_replay_bracket

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    stop_at, target_at, entry_at = Decimal("98"), Decimal("104"), Decimal("100")
    ticker = "AAPL"
    with Session(engine) as session:
        session.add(Symbol(ticker=ticker, name=ticker, currency="USD"))
        session.commit()
        for ts, (o, h, lo, c) in ((DAY1, (entry_at,) * 4), (DAY2, (OPEN, HIGH, LOW, CLOSE))):
            session.add(PriceBar(ticker=ticker, ts=ts, interval="1d", open=o, high=h, low=lo,
                                 close=c, volume=1000, source="test"))  # fmt: skip
        session.commit()
        uid = _user(session)
        replay = create_replay_session(session, user_id=uid, ticker=ticker, start_at=DAY1,
                                       end_at=DAY2, profile="intrabar_ohlc")  # fmt: skip
        placed = submit_replay_bracket(session, replay=replay, quantity=QTY, entry_type="market",
                                       stop_price=stop_at, target_price=target_at)  # fmt: skip
        assert placed.fill is not None and placed.fill.fill_price == entry_at
        before = placed.replay.cash_balance
        replay = advance_replay_session(session, replay=placed.replay)
        orders = {o.order_type: o for o in list_replay_orders(session, replay=replay)}
        assert orders["stop_loss"].status == "filled"
        assert orders["take_profit"].status == "cancelled"
        assert INTRABAR_UNKNOWN_LABEL in (orders["stop_loss"].reason or "")
        exit_fill = session.exec(
            select(ReplayFill).where(ReplayFill.order_id == orders["stop_loss"].id)
        ).one()
        replay_change = replay.cash_balance - before

    ledger = SimLedger(cash=Decimal(100_000))
    ledger.apply(OrderSide.BUY, ticker, QTY, entry_at)
    stop = OrderIntent(ticker=ticker, side=OrderSide.SELL, order_type=SimulationOrderType.STOP_LOSS,
                       quantity=QTY, submitted_at=DAY1.replace(tzinfo=UTC), limit_price=stop_at)  # fmt: skip
    target = OrderIntent(ticker=ticker, side=OrderSide.SELL,
                         order_type=SimulationOrderType.TAKE_PROFIT, quantity=QTY,
                         submitted_at=DAY1.replace(tzinfo=UTC), limit_price=target_at)  # fmt: skip
    bar = MarketSnapshot(ticker=ticker, observed_at=DAY2.replace(tzinfo=UTC), interval="1d",
                         open=OPEN, high=HIGH, low=LOW, close=CLOSE, volume=Decimal(1000))  # fmt: skip
    result = evaluate_oco_exit(stop, target, bar, INTRABAR_OHLC)
    assert result.leg == "stop" and result.order_unknown
    cash_before = ledger.cash
    ledger.apply(OrderSide.SELL, ticker, QTY, result.decision.fill_price or Decimal(0))
    assert exit_fill.fill_price == result.decision.fill_price == stop_at
    assert replay_change == ledger.cash - cash_before
