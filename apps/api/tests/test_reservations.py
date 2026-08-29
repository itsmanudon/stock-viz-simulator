"""Buying-power and share-reservation invariants for pending orders.

Reservations are derived from PENDING orders. These tests pin the financial
integrity rules: later spends cannot consume reserved cash/shares; a filling
order may use its own reservation but not another order's; cancel/fill
releases the reservation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine, select

from stockviz.models import (
    FxRate,
    OptionType,
    PendingOrder,
    Portfolio,
    PriceBar,
    Symbol,
    TradeSide,
    User,
)
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.options.trade import (
    InsufficientCashForOption,
    open_option,
    settle_expired_options,
)
from stockviz.services.simulation import LEGACY_CLOSE, ExecutionTrace, FillDecision, FillStatus
from stockviz.services.trading import (
    DEFAULT_STARTING_CASH,
    InsufficientCash,
    InsufficientPosition,
    NoFxRateError,
    cancel_pending_order,
    compute_portfolio,
    create_pending_order,
    ensure_default_portfolio,
    execute_trade,
    settle_pending_orders,
)
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    lock_portfolio,
    reserved_cash,
    reserved_shares,
)
from stockviz.services.trading.execute import get_position, resolve_priced_symbol
from stockviz.services.trading.execution_provenance import FillProvenance
from stockviz.services.trading.orders import _fill

BAR_DATE = datetime(2025, 4, 10)
BAR_DAY = BAR_DATE.date()


def _user(session: Session, email: str = "reserve@stockviz.dev") -> int:
    user = User(email=email, name="Reserver")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbol(
    session: Session,
    ticker: str,
    *,
    currency: str = "USD",
    close: Decimal = Decimal("150"),
    ts: datetime = BAR_DATE,
) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency=currency))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=ts,
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


def _fx(session: Session, currency: str, usd_rate: str) -> None:
    session.add(FxRate(currency=currency, date=BAR_DAY, usd_rate=Decimal(usd_rate)))
    session.commit()


def _portfolio(session: Session, user_id: int) -> Portfolio:
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    return portfolio


def _pid(portfolio: Portfolio) -> int:
    assert portfolio.id is not None
    return portfolio.id


def _pending_buy(
    session: Session,
    user_id: int,
    *,
    ticker: str = "AAPL",
    quantity: Decimal,
    limit_price: Decimal,
) -> PendingOrder:
    return create_pending_order(
        session,
        user_id=user_id,
        ticker=ticker,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
    )


def _pending_sell(
    session: Session,
    user_id: int,
    *,
    ticker: str = "AAPL",
    quantity: Decimal,
    limit_price: Decimal,
    order_type: OrderType = OrderType.LIMIT,
) -> PendingOrder:
    return create_pending_order(
        session,
        user_id=user_id,
        ticker=ticker,
        side=TradeSide.SELL,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
    )


# ---------------------------------------------------------------------------
# Pending BUY
# ---------------------------------------------------------------------------


def test_pending_buy_reserves_buying_power(session: Session) -> None:
    """Test 1 — one reservation: 80k reserved, 20k available."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))

    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH
    assert reserved_cash(session, _pid(portfolio)) == Decimal("80000.000000")
    assert available_cash(session, portfolio) == Decimal("20000.000000")


def test_second_pending_buy_rejected_when_buying_power_insufficient(session: Session) -> None:
    """Test 2 — pending BUY A = 80k, B = 30k is rejected."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    _portfolio(session, user_id)

    _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))
    with pytest.raises(InsufficientCash, match="Available buying power"):
        _pending_buy(session, user_id, quantity=Decimal(300), limit_price=Decimal("100"))


def test_pending_buy_exact_remaining_cash_accepted(session: Session) -> None:
    """Test 3 — A reserves 80k, B reserves remaining 20k."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))
    _pending_buy(session, user_id, quantity=Decimal(200), limit_price=Decimal("100"))

    session.refresh(portfolio)
    assert reserved_cash(session, _pid(portfolio)) == Decimal("100000.000000")
    assert available_cash(session, portfolio) == Decimal("0.000000")


def test_cancel_releases_buy_reservation(session: Session) -> None:
    """Test 4 — cancelling a pending BUY returns available cash to the full balance."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    order = _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))
    order.status = OrderStatus.CANCELLED
    session.add(order)
    session.commit()

    session.refresh(portfolio)
    assert reserved_cash(session, _pid(portfolio)) == Decimal("0")
    assert available_cash(session, portfolio) == DEFAULT_STARTING_CASH


def test_fill_releases_buy_reservation_and_debits_cash(session: Session) -> None:
    """Test 5 — after a fill the order no longer contributes to reserved cash."""
    _symbol(session, "AAPL", close=Decimal("100"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    order = _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))
    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 1

    session.refresh(order)
    session.refresh(portfolio)
    assert order.status == OrderStatus.FILLED
    assert reserved_cash(session, _pid(portfolio)) == Decimal("0")
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("80000.000000")
    pos = get_position(session, portfolio_id=_pid(portfolio), ticker="AAPL")
    assert pos is not None
    assert pos.quantity == Decimal(800)


def test_market_buy_cannot_steal_reserved_cash(session: Session) -> None:
    """Test 6 — pending BUY 80k, market BUY costing 30k is rejected."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    _portfolio(session, user_id)

    _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))
    with pytest.raises(InsufficientCash, match="Available buying power"):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(200)
        )


def test_option_purchase_cannot_steal_reserved_cash(session: Session) -> None:
    """Test 7 — pending BUY 80k, option premium above remaining 20k is rejected."""
    _symbol(session, "AAPL", close=Decimal("150"))
    # Enough history for Black-Scholes vol.
    for i in range(1, 40):
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=BAR_DATE - timedelta(days=i),
                interval="1d",
                open=Decimal("150"),
                high=Decimal("151"),
                low=Decimal("149"),
                close=Decimal("150"),
                volume=1_000,
                source="test",
            )
        )
    session.commit()

    user_id = _user(session)
    _portfolio(session, user_id)
    _pending_buy(session, user_id, quantity=Decimal(800), limit_price=Decimal("100"))

    with pytest.raises(InsufficientCashForOption, match="Available buying power"):
        open_option(
            session,
            user_id=user_id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal("50"),
            expiry=date.today() + timedelta(days=30),
            quantity=3,
        )


def test_settling_order_can_consume_its_own_reservation(session: Session) -> None:
    """Test 8 — a fill is not rejected merely because its own reservation reduces available_cash."""
    _symbol(session, "AAPL", close=Decimal("100"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    # Reserves the entire 100k. General available_cash is 0; the fill must still proceed.
    order = _pending_buy(session, user_id, quantity=Decimal(1000), limit_price=Decimal("100"))
    assert available_cash(session, portfolio) == Decimal("0")
    assert available_cash(session, portfolio, exclude_order_id=order.id) == DEFAULT_STARTING_CASH

    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 1
    session.refresh(order)
    assert order.status == OrderStatus.FILLED


def test_settlement_respects_other_orders_reservations(session: Session) -> None:
    """Test 9 — A may use its reservation; leftover cash stays reserved for B."""
    _symbol(session, "AAPL", close=Decimal("100"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    order_a = _pending_buy(session, user_id, quantity=Decimal(600), limit_price=Decimal("100"))
    order_b = _pending_buy(session, user_id, quantity=Decimal(400), limit_price=Decimal("100"))

    # Only A is in range of this close: bump B's ticker... both are AAPL.
    # Both trigger at close 100 <= 100. A is processed first (creation order).
    # After A fills at $60k, cash is $40k and B's $40k reservation still holds,
    # so a subsequent market buy must be rejected.
    filled = settle_pending_orders(session, session_date=BAR_DAY)
    # Both can fill using their own reservations (100k covers 60k+40k).
    assert filled == 2
    session.refresh(order_a)
    session.refresh(order_b)
    session.refresh(portfolio)
    assert order_a.status == OrderStatus.FILLED
    assert order_b.status == OrderStatus.FILLED
    assert portfolio.cash_balance == Decimal("0.000000")


def test_settlement_does_not_spend_another_orders_buying_power(session: Session) -> None:
    """A triggered BUY cannot consume cash reserved by a still-pending sibling.

    B is a buy whose limit is above the close (does not trigger). A's fill at
    $60k must leave B's $40k reservation intact, so a $30k market buy fails.
    """
    _symbol(session, "AAPL", close=Decimal("100"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    _pending_buy(session, user_id, quantity=Decimal(600), limit_price=Decimal("100"))
    _pending_buy(session, user_id, quantity=Decimal(400), limit_price=Decimal("50"))

    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 1
    session.refresh(portfolio)
    assert reserved_cash(session, _pid(portfolio)) == Decimal("20000.000000")
    assert available_cash(session, portfolio) == Decimal("20000.000000")

    with pytest.raises(InsufficientCash):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(300)
        )


# ---------------------------------------------------------------------------
# Pending SELL
# ---------------------------------------------------------------------------


def test_second_pending_sell_rejected_when_shares_reserved(session: Session) -> None:
    """Test 10 — position 100, pending SELL 60, second SELL 50 is rejected."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    _pending_sell(session, user_id, quantity=Decimal(60), limit_price=Decimal("160"))
    with pytest.raises(InsufficientPosition, match="reserved"):
        _pending_sell(session, user_id, quantity=Decimal(50), limit_price=Decimal("160"))


def test_market_sell_cannot_steal_reserved_shares(session: Session) -> None:
    """Test 11 — pending SELL 60, market SELL 50 is rejected."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    _pending_sell(session, user_id, quantity=Decimal(60), limit_price=Decimal("160"))
    with pytest.raises(InsufficientPosition, match="reserved"):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(50)
        )


def test_market_sell_of_unreserved_shares_allowed(session: Session) -> None:
    """Test 12 — pending SELL 60 of 100, market SELL 40 is allowed."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    _pending_sell(session, user_id, quantity=Decimal(60), limit_price=Decimal("160"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(40)
    )

    portfolio = _portfolio(session, user_id)
    pos = get_position(session, portfolio_id=_pid(portfolio), ticker="AAPL")
    assert pos is not None
    assert pos.quantity == Decimal(60)
    assert reserved_shares(session, _pid(portfolio), "AAPL") == Decimal(60)
    assert available_shares(session, _pid(portfolio), "AAPL") == Decimal(0)


def test_cancel_releases_sell_reservation(session: Session) -> None:
    """Test 13 — cancelling a pending SELL makes all remaining shares available."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    order = _pending_sell(session, user_id, quantity=Decimal(60), limit_price=Decimal("160"))
    order.status = OrderStatus.CANCELLED
    session.add(order)
    session.commit()

    portfolio = _portfolio(session, user_id)
    assert reserved_shares(session, _pid(portfolio), "AAPL") == Decimal(0)
    assert available_shares(session, _pid(portfolio), "AAPL") == Decimal(100)


def test_triggered_pending_sell_can_consume_its_own_shares(session: Session) -> None:
    """Test 14 — a triggered SELL is not blocked by its own reserved quantity."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    order = _pending_sell(
        session,
        user_id,
        quantity=Decimal(100),
        limit_price=Decimal("150"),
        order_type=OrderType.TAKE_PROFIT,
    )
    portfolio = _portfolio(session, user_id)
    assert available_shares(session, _pid(portfolio), "AAPL") == Decimal(0)
    assert available_shares(session, _pid(portfolio), "AAPL", exclude_order_id=order.id) == Decimal(
        100
    )

    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 1
    session.refresh(order)
    assert order.status == OrderStatus.FILLED
    assert get_position(session, portfolio_id=_pid(portfolio), ticker="AAPL") is None


def test_pending_sell_without_position_rejected(session: Session) -> None:
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    with pytest.raises(InsufficientPosition):
        _pending_sell(session, user_id, quantity=Decimal(1), limit_price=Decimal("160"))


def test_stop_loss_and_take_profit_reserve_shares(session: Session) -> None:
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )

    _pending_sell(
        session,
        user_id,
        quantity=Decimal(40),
        limit_price=Decimal("120"),
        order_type=OrderType.STOP_LOSS,
    )
    _pending_sell(
        session,
        user_id,
        quantity=Decimal(40),
        limit_price=Decimal("200"),
        order_type=OrderType.TAKE_PROFIT,
    )
    with pytest.raises(InsufficientPosition):
        _pending_sell(session, user_id, quantity=Decimal(30), limit_price=Decimal("160"))


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------


def test_non_usd_pending_buy_reserves_usd_equivalent(session: Session) -> None:
    """GBP limit * qty * USD-per-GBP rate is the reserved USD buying power."""
    _symbol(session, "BARC.L", currency="GBP", close=Decimal("100"))
    _fx(session, "GBP", "1.30")
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    _pending_buy(
        session, user_id, ticker="BARC.L", quantity=Decimal(10), limit_price=Decimal("100")
    )

    session.refresh(portfolio)
    assert reserved_cash(session, _pid(portfolio)) == Decimal("1300.000000")
    assert available_cash(session, portfolio) == DEFAULT_STARTING_CASH - Decimal("1300.000000")


def test_pending_buy_missing_fx_is_rejected(session: Session) -> None:
    _symbol(session, "SAP.DE", currency="EUR", close=Decimal("120"))
    user_id = _user(session)
    with pytest.raises(NoFxRateError):
        _pending_buy(
            session, user_id, ticker="SAP.DE", quantity=Decimal(10), limit_price=Decimal("100")
        )


def test_fill_revalidates_when_fx_moves_against_reservation(session: Session) -> None:
    """Reservation used fx=1.10; fill uses a worse rate and must not spend B's cash."""
    _symbol(session, "SAP.DE", currency="EUR", close=Decimal("100"))
    _fx(session, "EUR", "1.10")
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)

    # A: 600 * €100 * 1.10 = $66,000 reserved
    _pending_buy(
        session, user_id, ticker="SAP.DE", quantity=Decimal(600), limit_price=Decimal("100")
    )
    # B: 300 * €100 * 1.10 = $33,000 reserved (does not trigger: limit 50 < close 100)
    _pending_buy(
        session, user_id, ticker="SAP.DE", quantity=Decimal(300), limit_price=Decimal("50")
    )

    # FX jumps; A's fill would cost 600 * 100 * 1.50 = $90,000.
    # Spendable for A = 100k - B's current reservation (300*100*1.50=$45k) = $55k.
    today = date.today()
    session.add(FxRate(currency="EUR", date=today, usd_rate=Decimal("1.50")))
    session.commit()

    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 0
    session.refresh(portfolio)
    # Cash untouched; both orders still account for reservations at the new rate,
    # or A was cancelled for insufficient buying power.
    pending = list(session.exec(select(PendingOrder)).all())
    statuses = {o.quantity: o.status for o in pending}
    # A (600) should have been cancelled; B (300) stays pending.
    assert statuses[Decimal("600")] == OrderStatus.CANCELLED
    assert statuses[Decimal("300")] == OrderStatus.PENDING
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH


# ---------------------------------------------------------------------------
# Portfolio snapshot + option exercise fallback
# ---------------------------------------------------------------------------


def test_compute_portfolio_exposes_reservation_fields(session: Session) -> None:
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    _pending_buy(session, user_id, quantity=Decimal(100), limit_price=Decimal("100"))
    _pending_sell(session, user_id, quantity=Decimal(4), limit_price=Decimal("200"))

    portfolio = _portfolio(session, user_id)
    snap = compute_portfolio(session, portfolio)
    assert snap.reserved_cash == Decimal("10000.000000")
    assert snap.available_cash == portfolio.cash_balance - Decimal("10000.000000")
    pos = snap.positions[0]
    assert pos.reserved_quantity == Decimal(4)
    assert pos.available_quantity == Decimal(6)


def test_itm_call_cash_settles_when_cash_is_reserved(session: Session) -> None:
    """ITM call exercise falls back to cash settlement when available_cash < strike."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)
    # Reserve almost all cash so strike cost $10,000 cannot be taken from available.
    _pending_buy(session, user_id, quantity=Decimal(950), limit_price=Decimal("100"))

    from stockviz.models import OptionsPosition, OptionStatus

    pos = OptionsPosition(
        user_id=user_id,
        portfolio_id=_pid(portfolio),
        ticker="AAPL",
        option_type=OptionType.CALL,
        strike=Decimal(100),
        expiry=BAR_DAY,
        quantity=1,
        premium_paid=Decimal("500.00"),
        status=OptionStatus.OPEN,
    )
    session.add(pos)
    session.commit()

    settle_expired_options(session, settle_date=BAR_DAY)
    session.refresh(pos)
    session.refresh(portfolio)
    assert pos.status == OptionStatus.EXERCISED
    # Cash-settled intrinsic: (150-100)*100 = $5,000 credited, equity not opened.
    assert get_position(session, portfolio_id=_pid(portfolio), ticker="AAPL") is None
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + Decimal("5000.00")


def test_itm_put_cash_settles_when_shares_are_reserved(session: Session) -> None:
    """ITM put falls back to cash settlement when available shares are reserved."""
    _symbol(session, "AAPL", close=Decimal("80"))
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(100)
    )
    _pending_sell(session, user_id, quantity=Decimal(100), limit_price=Decimal("200"))

    from stockviz.models import OptionsPosition, OptionStatus

    portfolio = _portfolio(session, user_id)
    opening_cash = portfolio.cash_balance
    pos = OptionsPosition(
        user_id=user_id,
        portfolio_id=_pid(portfolio),
        ticker="AAPL",
        option_type=OptionType.PUT,
        strike=Decimal(100),
        expiry=BAR_DAY,
        quantity=1,
        premium_paid=Decimal("500.00"),
        status=OptionStatus.OPEN,
    )
    session.add(pos)
    session.commit()

    settle_expired_options(session, settle_date=BAR_DAY)
    session.refresh(pos)
    session.refresh(portfolio)
    assert pos.status == OptionStatus.EXERCISED
    # Shares still held (reserved); intrinsic (100-80)*100 = $2,000 credited.
    held = get_position(session, portfolio_id=_pid(portfolio), ticker="AAPL")
    assert held is not None
    assert held.quantity == Decimal(100)
    assert portfolio.cash_balance == opening_cash + Decimal("2000.00")


# ---------------------------------------------------------------------------
# Locking / concurrency intent
# ---------------------------------------------------------------------------


def test_lock_portfolio_emits_for_update() -> None:
    """Postgres compiles the portfolio lock as SELECT ... FOR UPDATE.

    ``lock_portfolio`` uses ``Session.refresh(..., with_for_update=True)``.
    SQLite ignores the clause; concurrent over-commit is covered by
    ``test_pg_concurrency.py`` when DATABASE_URL points at PostgreSQL.
    """
    stmt = select(Portfolio).where(Portfolio.id == 1).with_for_update()
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled.upper()


def test_lock_portfolio_returns_the_row(session: Session) -> None:
    user_id = _user(session)
    portfolio = _portfolio(session, user_id)
    locked = lock_portfolio(session, _pid(portfolio))
    assert locked.id == portfolio.id
    assert locked.cash_balance == DEFAULT_STARTING_CASH


def test_lock_portfolio_refreshes_stale_identity_map(tmp_path: Path) -> None:
    """A FOR UPDATE lock must overwrite cash already sitting in the Session.

    ``ensure_default_portfolio`` loads the row before ``lock_portfolio``.
    Without refresh/populate_existing, a concurrent debit that committed
    while this session waited would be ignored and then overwritten.
    """
    import stockviz.models  # noqa: F401 — register metadata

    engine = create_engine(
        f"sqlite:///{tmp_path / 'lock.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as setup:
            user_id = _user(setup)
            pid = _pid(_portfolio(setup, user_id))

        with Session(engine) as s1:
            loaded = s1.get(Portfolio, pid)
            assert loaded is not None
            assert loaded.cash_balance == DEFAULT_STARTING_CASH
            with Session(engine) as s2:
                other = s2.get(Portfolio, pid)
                assert other is not None
                other.cash_balance = Decimal("1.000000")
                s2.add(other)
                s2.commit()
            locked = lock_portfolio(s1, pid)
            assert locked.cash_balance == Decimal("1.000000")
            assert loaded.cash_balance == Decimal("1.000000")
    finally:
        engine.dispose()


def test_fill_skips_order_that_is_no_longer_pending(session: Session) -> None:
    """Settlement must re-check status after the portfolio lock."""
    _symbol(session, "AAPL", close=Decimal("150"))
    user_id = _user(session)
    order = _pending_buy(session, user_id, quantity=Decimal(10), limit_price=Decimal("200"))
    assert order.id is not None
    cancel_pending_order(session, user_id=user_id, order_id=order.id)
    session.refresh(order)
    priced = resolve_priced_symbol(session, "AAPL")
    dummy = FillDecision(
        status=FillStatus.FILLED,
        fill_quantity=order.quantity,
        fill_price=priced.price,
        remaining_quantity=Decimal(0),
        trace=ExecutionTrace(
            profile=LEGACY_CLOSE.name,
            model_version=LEGACY_CLOSE.model_version,
            reference_price=priced.price,
            fill_price=priced.price,
            reason="unused: order already cancelled",
            assumptions=LEGACY_CLOSE.assumptions,
        ),
    )
    provenance = FillProvenance(
        decision=dummy,
        market_interval=priced.bar.interval,
        evaluated_at=datetime.now(UTC),
        order_type=order.order_type.value,
    )
    assert _fill(session, order, priced, fill_price=priced.price, provenance=provenance) is False
    session.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    portfolio = _portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH
