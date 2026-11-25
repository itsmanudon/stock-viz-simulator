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
the realised P&L. Live and replay book no fees, so for a fee schedule the
backtest's cash change must equal the live one less exactly the schedule's
fee on that same fill.

What a path does not support is a skip with its reason (never silent):
live is pinned to ``legacy_close``; replay is pinned to ``legacy_close`` and
USD-only; ``next_open`` exists only in backtests (it is compared against the
kernel's own rule in :func:`test_next_open_backtest_path`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz.models import FxRate, Portfolio, PriceBar, Symbol, Trade, TradeSide, User
from stockviz.models.order import OrderType
from stockviz.services.backtest.fills import book
from stockviz.services.replay import (
    advance_replay_session,
    create_replay_session,
    submit_replay_order,
)
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    NEXT_OPEN,
    ExecutionProfile,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimLedger,
    SimulationOrderType,
    evaluate_order,
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
    "USD": ("none", "us_equity_2026"),
    "INR": ("none", "in_delivery_nse_2026", "in_delivery_bse_2026"),
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
    Order("limit_buy_not_triggered", OrderSide.BUY, SimulationOrderType.LIMIT, Decimal("99")),
    Order("limit_sell", OrderSide.SELL, SimulationOrderType.LIMIT, Decimal("99.5")),
    Order("stop_sell", OrderSide.SELL, SimulationOrderType.STOP_LOSS, Decimal("100.5")),
)


@dataclass(frozen=True)
class Fill:
    price: Decimal
    quantity: Decimal
    cash_change: Decimal  # in the symbol's currency
    realized: Decimal | None


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
        kind = OrderType.LIMIT if order.kind is SimulationOrderType.LIMIT else OrderType.STOP_LOSS
        create_pending_order(session, user_id=uid, ticker=ticker, side=side, order_type=kind,
                             quantity=QTY, limit_price=order.limit)  # fmt: skip
        settle_pending_orders(session, session_date=DAY2.date())
    trade = session.exec(select(Trade).where(col(Trade.id).not_in(before))).first()
    if trade is None:
        return None
    native = (trade.price * trade.quantity).quantize(MICROS)
    change = -native if trade.side == TradeSide.BUY else native
    if currency == "USD":
        session.expire_all()
        after = session.get(Portfolio, portfolio.id).cash_balance  # type: ignore[union-attr]
        assert after - cash_before == change
    realized = trade.realized_pnl if currency == "USD" else None
    return Fill(trade.price, trade.quantity, change, realized)


def replay_fill(session: Session, currency: str, order: Order) -> Fill | None:
    ticker = _seed(session, currency)
    uid = _user(session)
    replay = create_replay_session(session, user_id=uid, ticker=ticker, start_at=DAY1, end_at=DAY2)
    if order.side is OrderSide.SELL:
        submit_replay_order(session, replay=replay, side=OrderSide.BUY,
                            order_type=SimulationOrderType.MARKET, quantity=HELD)  # fmt: skip
    replay = advance_replay_session(session, replay=replay)
    before = replay.cash_balance
    result = submit_replay_order(session, replay=replay, side=order.side, order_type=order.kind,
                                 quantity=QTY, limit_price=order.limit)  # fmt: skip
    if result.fill is None:
        return None
    return Fill(result.fill.fill_price, result.fill.quantity,
                result.replay.cash_balance - before, result.fill.realized_pnl)  # fmt: skip


def backtest_fill(
    currency: str, order: Order, profile: ExecutionProfile, fee_schedule: str
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
    booked = book(ledger, intent, bar, profile, schedule=get_fee_schedule(fee_schedule))
    if booked is None:
        return None, Decimal(0)
    return (
        Fill(booked.price, booked.fill.quantity, booked.cash_change, booked.fill.realized_pnl),
        booked.fees.total,
    )


def _agree(path: Fill | None, currency: str, order: Order, fee_schedule: str) -> None:
    backtest, fees = backtest_fill(currency, order, LEGACY_CLOSE, fee_schedule)
    assert (path is None) == (backtest is None), (order.name, fee_schedule)
    if path is None or backtest is None:
        return
    assert (backtest.price, backtest.quantity) == (path.price, path.quantity)
    expected_fees = get_fee_schedule(fee_schedule).fees(order.side, path.quantity, path.price).total
    assert fees == expected_fees.quantize(MICROS)
    assert backtest.cash_change == path.cash_change - fees, (order.name, fee_schedule)
    if path.realized is not None:
        assert backtest.realized == path.realized


SKIPS = {
    (
        "live",
        "next_open",
    ): "live paper trading is pinned to legacy_close (LIVE_PAPER_EXECUTION_PROFILE)",
    ("replay", "next_open"): "replay sessions are pinned to legacy_close",
    ("replay", "legacy_close", "INR"): "replay is USD-only until A4.6 (replay in INR)",
}


@pytest.mark.parametrize("currency", ["USD", "INR"])
@pytest.mark.parametrize("profile", ["legacy_close", "next_open"])
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
            fill = (live_fill if path == "live" else replay_fill)(session, currency, order)
        assert (fill is None) == (order.name == "limit_buy_not_triggered"), order.name
        for fee_schedule in FEES[currency]:
            _agree(fill, currency, order, fee_schedule)


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
    assert live == replay == backtest and fees == 0
    assert live is not None and live.price == CLOSE and live.cash_change == -(CLOSE * QTY)


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
