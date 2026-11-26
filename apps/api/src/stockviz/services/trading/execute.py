"""Trade execution.

A market order fills at the most recent ``1d`` close in ``price_bars``. The
fill *price* is decided by ``evaluate_order(..., LEGACY_CLOSE)`` (SIM-02).
Cash, shares, FX, and the ledger still mutate only in :func:`apply_fill`,
which is shared with the pending-order settlement job in
``services/trading/orders.py``. Both paths must debit the *USD* cash bucket
at the symbol's FX rate — keeping that in one place is what stops the two
from drifting apart.

Pending limit/stop/take-profit settlement also uses the kernel (SIM-03);
account mutations still go through :func:`apply_fill`. Successful fills
persist ``SimulatedExecution`` provenance from the same FillDecision
(SIM-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.models import FxConversion, Portfolio, Position, PriceBar, Symbol, Trade, TradeSide
from stockviz.models.trade_plan import TradePlan
from stockviz.schemas import TradePlanDraft
from stockviz.services.instruments import instrument_of, is_index_ticker
from stockviz.services.simulation import (
    LIVE_PAPER_EXECUTION_PROFILE,
    FeeBreakdown,
    FillDecision,
    FillStatus,
    OrderIntent,
    SimulationOrderType,
    evaluate_order,
    get_fee_schedule,
)
from stockviz.services.trading.books import (
    DEFAULT_STARTING_CASH as DEFAULT_STARTING_CASH,
)
from stockviz.services.trading.books import (
    ensure_default_portfolio as ensure_default_portfolio,
)
from stockviz.services.trading.books import (
    resolve_book,
)
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    lock_portfolio,
    reserved_shares,
)
from stockviz.services.trading.cash import base_currency, pay_for_buy, plan_buy
from stockviz.services.trading.cash import credit as credit_cash
from stockviz.services.trading.execution_provenance import (
    FillProvenance,
    record_execution_provenance,
)
from stockviz.services.trading.fx import StaleFxRate, fill_rate_to_base, latest_rate
from stockviz.services.trading.simulation_adapter import (
    evaluation_clock,
    market_snapshot_from_bar,
    order_side,
)

logger = logging.getLogger(__name__)

EMPTY_FEES = FeeBreakdown(())


MICROS = Decimal("0.000001")
"""Quantization step for stored monetary values (matches Numeric(_, 6))."""


class TradeExecutionError(Exception):
    """Base class for things the caller should turn into a 400-shaped response."""


class SymbolNotFound(TradeExecutionError):
    pass


class NotTradable(TradeExecutionError):
    """An index (Phase 7.4) has stored closes but cannot be bought or sold."""


class NoMarketDataError(TradeExecutionError):
    pass


class NoFxRateError(TradeExecutionError):
    """Raised when a non-USD trade has no FX rate available to convert cost to USD."""


class InsufficientCash(TradeExecutionError):
    pass


class InsufficientPosition(TradeExecutionError):
    pass


class StaleMarketData(TradeExecutionError):
    """The symbol's latest close trails its market's newest close (#67)."""


class ClientOrderIdConflict(TradeExecutionError):
    """A client_order_id already names a different order in this portfolio (LG-10)."""


def newest_close_for_currency(session: Session, currency: str) -> datetime | None:
    """Newest ``1d`` bar among active symbols quoted in ``currency``.

    The market's current session without a holiday calendar: when a whole
    market is closed none of its symbols moves, so this stays put.
    """
    return session.exec(
        select(func.max(PriceBar.ts))
        .join(Symbol, col(PriceBar.instrument_id) == instrument_of(Symbol.ticker))
        .where(
            PriceBar.interval == "1d",
            Symbol.currency == currency,
            Symbol.is_active == True,  # noqa: E712
        )
    ).one()


def require_current_close(session: Session, priced: PricedSymbol) -> None:
    """Refuse a market fill at a close older than the symbol's market has (#67).

    The rule: a market order fills only when the symbol's newest close is from
    the same day as the newest close of any active symbol in its currency.
    A failed refresh for one ticker leaves it behind its peers, so it cannot be
    bought or sold at a days-old price. Weekends and market holidays move every
    peer together, so trading at Friday's close stays allowed. A refresh that
    failed for the whole market is not caught here; exchange calendars
    (Phase 4) give the absolute rule.
    """
    newest = newest_close_for_currency(session, priced.currency)
    bar_day = priced.bar.ts.date()
    if newest is not None and bar_day < newest.date():
        raise StaleMarketData(
            f"{priced.symbol.ticker}'s latest close is from {bar_day.isoformat()}, "
            f"but {priced.currency} markets have closes from {newest.date().isoformat()}. "
            "Its price refresh is behind, so market orders wait until it catches up."
        )


def latest_bar(session: Session, ticker: str) -> PriceBar | None:
    """Most recent ``1d`` bar for ``ticker``, or None when there is no history."""
    return session.exec(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()


def _latest_close(session: Session, ticker: str) -> Decimal | None:
    bar = latest_bar(session, ticker)
    return bar.close if bar else None


def get_position(session: Session, *, portfolio_id: int, ticker: str) -> Position | None:
    """Return the existing Position row for (portfolio, ticker), or None."""

    return session.exec(
        select(Position)
        .where(
            Position.portfolio_id == portfolio_id, Position.instrument_id == instrument_of(ticker)
        )
        .limit(1)
    ).first()


@dataclass(frozen=True, slots=True)
class PricedSymbol:
    """A symbol resolved to a fillable price plus the FX rate for its currency."""

    symbol: Symbol
    price: Decimal
    currency: str
    fx_rate: Decimal
    bar: PriceBar


def resolve_priced_symbol(
    session: Session,
    ticker: str,
    *,
    base: str = "USD",
    settled_session: date | None = None,
) -> PricedSymbol:
    """Look up the symbol, its latest close, and the FX rate into ``base``.

    ``base`` is the portfolio's base currency (Phase 4.8: USD or INR); the
    rate is units of ``base`` per unit of the symbol's currency.

    The rate is the newest stored one, refused when older than the session
    before the fill's own (MD-7): the latest completed session for a market
    order, ``settled_session`` for pending-order settlement.

    Raises the matching ``TradeExecutionError`` subclass when any leg is
    missing, so callers get one consistent failure vocabulary.
    """

    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise SymbolNotFound(f"Symbol {ticker!r} not found")
    if is_index_ticker(ticker):
        raise NotTradable(f"{ticker} is an index: it can be studied but not traded")

    bar = latest_bar(session, ticker)
    if bar is None:
        raise NoMarketDataError(f"No market data for {ticker!r}; cannot fill order")

    currency = symbol.currency or "USD"
    from stockviz._time import utcnow
    from stockviz.services.markets.calendar import venue_for_ticker

    try:
        fx_rate = fill_rate_to_base(
            session,
            currency,
            base,
            now=utcnow().replace(tzinfo=UTC),
            venue=venue_for_ticker(ticker),
            settled_session=settled_session,
        )
    except StaleFxRate as exc:
        raise NoFxRateError(f"{exc}; cannot price {ticker!r} trade in {base}") from exc
    except LookupError as exc:
        raise NoFxRateError(
            f"No FX rate for {currency!r}; cannot price {ticker!r} trade in {base}"
        ) from exc

    return PricedSymbol(symbol=symbol, price=bar.close, currency=currency, fx_rate=fx_rate, bar=bar)


@dataclass(frozen=True, slots=True)
class TradeExecution:
    """Result of a fill: the persisted Trade row plus FX metadata.

    The Trade row stores price + quantity in the symbol's native currency
    (e.g. EUR for SAP.DE). ``base_cost`` is the fill's value in the
    portfolio's base currency (``base_currency``, USD or INR since Phase 4.8);
    ``fx_rate`` is base units per native unit (1 when they match).
    """

    trade: Trade
    currency: str
    fx_rate: Decimal
    native_cost: Decimal
    base_cost: Decimal
    realized_pnl: Decimal | None
    base_currency: str = "USD"
    # True when a repeated client_order_id returned an earlier fill (LG-10).
    replayed: bool = False
    # A4.2: fees in the native currency (0 when the schedule charges none).
    fees: Decimal = Decimal(0)


def fill_fees(
    session: Session,
    *,
    portfolio_id: int,
    ticker: str,
    side: TradeSide,
    quantity: Decimal,
    price: Decimal,
    on: date,
) -> tuple[str, FeeBreakdown]:
    """A4.2: the default schedule's fees for a live fill on ``on`` (the venue
    date). Indian symbols pay their venue's delivery schedule (Zerodha
    brokerage model, free for delivery); other markets ``none``. The DP charge
    is due on the first sell of the scrip that venue day."""
    from stockviz.services.fee_view import day_bounds_utc, default_schedule_name

    name = default_schedule_name(ticker)
    schedule = get_fee_schedule(name)
    if not schedule.versions:
        return name, EMPTY_FEES
    dp_due = True
    if side == TradeSide.SELL:
        start, end = day_bounds_utc(ticker, on)
        earlier = session.exec(
            select(Trade.id).where(
                Trade.portfolio_id == portfolio_id,
                Trade.instrument_id == instrument_of(ticker),
                Trade.side == TradeSide.SELL,
                col(Trade.fees).is_not(None),
                col(Trade.ts) >= start,
                col(Trade.ts) < end,
            )
        ).first()
        dp_due = earlier is None
    fees = schedule.fees(order_side(side), quantity, price, on=on, dp_due=dp_due)
    return name, fees


def fee_lines_json(fees: FeeBreakdown) -> list[dict[str, Any]]:
    version = fees.version
    out: list[dict[str, Any]] = []
    for line in fees.lines:
        comp = line.component
        out.append(
            {
                "key": line.key,
                "label": comp.label if comp else "Brokerage",
                "amount": str(line.amount),
                "rate": comp.rate_text()
                if comp
                else (fees.brokerage.rate_text() if fees.brokerage else ""),
                "effective_from": version.effective_from.isoformat() if version else None,
                "source_url": comp.source.url
                if comp
                else (
                    fees.brokerage.source.url if fees.brokerage and fees.brokerage.source else None
                ),
            }
        )
    return out


def apply_fill(
    session: Session,
    *,
    portfolio: Portfolio,
    ticker: str,
    side: TradeSide,
    quantity: Decimal,
    price: Decimal,
    currency: str,
    fx_rate: Decimal,
    exclude_order_id: int | None = None,
    client_order_id: str | None = None,
    check_limits: bool = True,
    exclude_option_id: int | None = None,
    fee_on: date | None = None,
    charge_fees: bool = True,
    trade_plan: TradePlan | None = None,
) -> TradeExecution:
    """Mutate cash + position and stage the Trade row for ``portfolio``.

    Shared by market orders (:func:`execute_trade`) and by the EOD
    pending-order settlement job. Adds rows to the session but does **not**
    commit — the caller owns the transaction boundary, which lets the
    settlement job batch many fills together.

    ``price`` is in the symbol's native currency; ``fx_rate`` is units of the
    portfolio's base currency per one unit of it (Phase 4.8). Cash debits,
    reservations and realized P&L are in the base currency.

    Spendability is checked against *available* cash/shares (ledger balance
    minus reservations from *other* pending orders and short option legs).
    ``exclude_order_id`` lets a filling order consume its own reservation,
    and ``exclude_option_id`` lets an assigned short leg use its cover.

    Locks the portfolio row for the rest of the caller's transaction.

    Raises ``InsufficientCash`` / ``InsufficientPosition`` without having
    mutated anything, so a caller that catches the error can carry on with the
    same session.

    A4.2: fees (:func:`fill_fees`, the version in force on ``fee_on``, the
    venue date of the fill; default today there) are paid on top of a buy and
    netted from a sell's proceeds, in the symbol's currency. ``realized_pnl``
    stays the price gain; the trade row keeps the fees beside it.
    ``charge_fees=False`` (option exercise and assignment) books none.

    A5.4: ``trade_plan`` links the fill to that plan (its first fill locks
    it, ``services/plans``); a sell that empties the position closes the
    book's active plans in the instrument.
    """

    assert portfolio.id is not None
    portfolio_id = portfolio.id
    portfolio = lock_portfolio(session, portfolio_id)

    base = base_currency(portfolio)
    native_cost = (price * quantity).quantize(MICROS)
    base_cost = (native_cost * fx_rate).quantize(MICROS)
    if charge_fees:
        from stockviz._time import utcnow
        from stockviz.services.fee_view import fee_date

        on = fee_on if fee_on is not None else fee_date(ticker, utcnow())
        schedule_name, fee_breakdown = fill_fees(
            session, portfolio_id=portfolio_id, ticker=ticker, side=side,
            quantity=quantity, price=price, on=on,
        )  # fmt: skip
    else:
        schedule_name, fee_breakdown = "none", EMPTY_FEES
    fees = fee_breakdown.total.quantize(MICROS)
    conversion: FxConversion | None = None
    position = get_position(session, portfolio_id=portfolio_id, ticker=ticker)
    realized_pnl: Decimal | None = None
    avg_cost_at_fill: Decimal | None = None
    flat_instrument: int | None = None

    if side == TradeSide.BUY:
        try:
            spendable = available_cash(
                session,
                portfolio,
                exclude_order_id=exclude_order_id,
                exclude_option_id=exclude_option_id,
            )
        except LookupError as exc:
            raise NoFxRateError(str(exc)) from exc
        # Phase 4.5b: a non-base buy spends that currency's cash first and
        # converts only the shortfall from the base balance.
        funding = plan_buy(session, portfolio, currency, native_cost + fees, fx_rate)
        if spendable < funding.base_debit:
            raise InsufficientCash(
                f"Available buying power {base} {spendable:,.2f}; order requires "
                f"{base} {funding.base_debit:,.2f}."
            )
        if check_limits:
            # Phase 8.5: the account's own limits, before anything moves. Option
            # exercise passes check_limits=False: settlement is never refused.
            from stockviz.services.risk.limits import enforce_buy

            enforce_buy(
                session,
                portfolio,
                ticker=ticker,
                currency=currency,
                quantity=quantity,
                price=price,
                base_cost=base_cost,
                base_debit=funding.base_debit,
            )
        conversion = pay_for_buy(session, portfolio, currency, funding, fx_rate)

        if position is None:
            position = Position(
                portfolio_id=portfolio_id,
                ticker=ticker,
                quantity=quantity,
                avg_cost=price,
            )
            session.add(position)
        else:
            # Weighted-average cost recompute, in native currency (the
            # symbol's currency doesn't change between trades).
            total_cost = position.avg_cost * position.quantity + native_cost
            new_qty = position.quantity + quantity
            position.quantity = new_qty
            position.avg_cost = (total_cost / new_qty).quantize(MICROS)

    else:  # SELL
        held = position.quantity if position else Decimal(0)
        reserved = reserved_shares(
            session,
            portfolio_id,
            ticker,
            exclude_order_id=exclude_order_id,
            exclude_option_id=exclude_option_id,
        )
        spendable = available_shares(
            session,
            portfolio_id,
            ticker,
            exclude_order_id=exclude_order_id,
            exclude_option_id=exclude_option_id,
        )
        if spendable < quantity:
            if reserved > 0:
                raise InsufficientPosition(
                    f"Only {spendable} {ticker} shares are available; "
                    f"{reserved} are reserved by pending orders or covered calls."
                )
            raise InsufficientPosition(f"Held {held} {ticker}, cannot sell {quantity}")
        assert position is not None
        avg_cost_at_fill = position.avg_cost
        if fees > native_cost:
            raise TradeExecutionError(
                f"Fees of {currency} {fees:,.2f} exceed the sale's value of "
                f"{currency} {native_cost:,.2f}."
            )
        # The proceeds, net of fees, stay in the symbol's currency (Phase 4.5b).
        credit_cash(session, portfolio, currency, native_cost - fees)
        # Realized P&L against the weighted-average cost basis, in the base.
        realized_pnl = ((price - position.avg_cost) * quantity * fx_rate).quantize(MICROS)
        position.quantity = position.quantity - quantity
        # Don't recompute avg_cost on sells — keeps cost basis honest for
        # remaining shares. If the position is fully sold, delete the row so
        # the portfolio view stays clean.
        if position.quantity == 0:
            session.delete(position)
            flat_instrument = position.instrument_id

    trade = Trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        fx_rate=fx_rate,
        realized_pnl=realized_pnl,
        avg_cost_at_fill=avg_cost_at_fill,
        client_order_id=client_order_id,
        fees=fees if charge_fees else None,
        fee_schedule=schedule_name if charge_fees else None,
        fee_lines=fee_lines_json(fee_breakdown) if charge_fees else None,
    )
    session.add(trade)
    session.add(portfolio)
    # Assign trade.id without committing so the outbox row can reference it
    # in this same transaction. Kafka is not involved here.
    session.flush()
    if conversion is not None:
        conversion.trade_id = trade.id
        session.add(conversion)
    if trade_plan is not None:
        from stockviz.services.plans import link_trade

        link_trade(session, trade_plan, trade)
    if flat_instrument is not None:
        from stockviz.services.plans import close_flat_plans

        close_flat_plans(session, portfolio_id=portfolio_id, instrument_id=flat_instrument)
    from stockviz.events.outbox import enqueue_trade_executed

    enqueue_trade_executed(
        session,
        trade=trade,
        currency=currency,
        fx_rate=fx_rate,
        usd_notional=_usd_value(session, base_cost, base),
    )
    return TradeExecution(
        trade=trade,
        currency=currency,
        fx_rate=fx_rate,
        native_cost=native_cost,
        base_cost=base_cost,
        realized_pnl=realized_pnl,
        base_currency=base,
        fees=fees,
    )


def _usd_value(session: Session, amount: Decimal, currency: str) -> Decimal:
    """``amount`` in USD at the latest rate, for the trade event's notional.

    The event contract names a USD notional; for an INR book it is an
    estimate, and the amount itself when no rate is stored.
    """
    if currency == "USD":
        return amount
    try:
        return (amount * latest_rate(session, currency)).quantize(MICROS)
    except LookupError:
        return amount


def execute_trade(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    side: TradeSide,
    quantity: Decimal,
    client_order_id: str | None = None,
    book_id: int | None = None,
    trade_plan_id: int | None = None,
    plan: TradePlanDraft | None = None,
) -> TradeExecution:
    """Execute a market order in ``book_id`` (default: the user's default book). Raises a ``TradeExecutionError`` subclass on validation failure.

    The price stored on the Trade row is in the symbol's native currency.
    Cash is debited/credited in the portfolio's base currency (Phase 4.8),
    converted at the fill's FX rate when the symbol trades in another one.

    Fill price comes from the SIM-01 kernel (``LIVE_PAPER_EXECUTION_PROFILE``,
    currently ``LEGACY_CLOSE``). Account validity, FX, and persistence stay in
    :func:`apply_fill`. Provenance is recorded from the same ``FillDecision``.

    With a ``client_order_id`` the order runs at most once per portfolio: a
    repeat with the same ticker, side and quantity returns the first fill
    (``replayed``), and a repeat naming a different order raises
    :class:`ClientOrderIdConflict` (#67, audit LG-10). The lookup runs under
    the portfolio lock, so two concurrent repeats cannot both fill.
    """

    if quantity <= 0:
        raise TradeExecutionError("quantity must be positive")

    ticker = ticker.upper()
    portfolio = resolve_book(session, user_id, book_id, write=True)
    assert portfolio.id is not None
    if client_order_id is not None:
        lock_portfolio(session, portfolio.id)
        earlier = session.exec(
            select(Trade).where(
                Trade.portfolio_id == portfolio.id,
                Trade.client_order_id == client_order_id,
            )
        ).first()
        if earlier is not None:
            return _replay_trade(session, earlier, ticker=ticker, side=side, quantity=quantity)

    priced = resolve_priced_symbol(session, ticker, base=base_currency(portfolio))
    require_current_close(session, priced)
    provenance = _market_fill_provenance(bar=priced.bar, side=side, quantity=quantity)
    fill_price = provenance.decision.fill_price
    assert fill_price is not None
    trade_plan = order_plan(
        session, user_id=user_id, book=portfolio, ticker=ticker, side=side,
        trade_plan_id=trade_plan_id, draft=plan,
    )  # fmt: skip

    try:
        result = apply_fill(
            session,
            portfolio=portfolio,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=fill_price,
            currency=priced.currency,
            fx_rate=priced.fx_rate,
            client_order_id=client_order_id,
            fee_on=_fee_on(ticker, provenance.evaluated_at),
            trade_plan=trade_plan,
        )
    except Exception:
        if plan is not None:
            session.rollback()  # the new plan goes with the refused order
        raise
    record_execution_provenance(session, trade=result.trade, provenance=provenance)
    session.commit()
    session.refresh(result.trade)
    return result


def order_plan(
    session: Session,
    *,
    user_id: int,
    book: Portfolio,
    ticker: str,
    side: TradeSide,
    trade_plan_id: int | None,
    draft: TradePlanDraft | None,
) -> TradePlan | None:
    """A5.4: the plan an order links to (``services/plans.plan_for_order``)."""
    if trade_plan_id is None and draft is None:
        return None
    from stockviz.services.instruments import resolve_symbol
    from stockviz.services.plans import plan_for_order

    instrument = resolve_symbol(session, ticker)
    if instrument is None or instrument.id is None:
        raise SymbolNotFound(f"Symbol {ticker!r} not found")
    return plan_for_order(
        session, user_id=user_id, book=book, instrument_id=instrument.id, side=side,
        trade_plan_id=trade_plan_id, draft=draft,
    )  # fmt: skip


def _fee_on(ticker: str, instant: datetime) -> date:
    from stockviz.services.fee_view import fee_date

    return fee_date(ticker, instant)


def _replay_trade(
    session: Session, trade: Trade, *, ticker: str, side: TradeSide, quantity: Decimal
) -> TradeExecution:
    """The earlier fill for a repeated client_order_id, priced as it was filled."""
    if trade.ticker != ticker or trade.side != side or trade.quantity != quantity:
        raise ClientOrderIdConflict(
            "This client_order_id was already used for a different order "
            f"({trade.side.value} {trade.quantity} {trade.ticker})."
        )
    session.rollback()  # release the portfolio lock; nothing was written
    symbol = session.get(Symbol, trade.ticker)
    currency = (symbol.currency if symbol else None) or "USD"
    fx_rate = trade.fx_rate if trade.fx_rate is not None else Decimal(1)
    native_cost = (trade.price * trade.quantity).quantize(MICROS)
    portfolio = session.get(Portfolio, trade.portfolio_id)
    return TradeExecution(
        trade=trade,
        currency=currency,
        fx_rate=fx_rate,
        native_cost=native_cost,
        base_cost=(native_cost * fx_rate).quantize(MICROS),
        realized_pnl=trade.realized_pnl,
        base_currency=base_currency(portfolio) if portfolio is not None else "USD",
        replayed=True,
        fees=trade.fees or Decimal(0),
    )


def _market_fill_provenance(*, bar: PriceBar, side: TradeSide, quantity: Decimal) -> FillProvenance:
    """Ask the live paper profile for a MARKET fill. Does not touch the ledger."""

    evaluated_at = evaluation_clock()
    order = OrderIntent(
        ticker=bar.ticker,
        side=order_side(side),
        order_type=SimulationOrderType.MARKET,
        quantity=quantity,
        remaining_quantity=quantity,
        submitted_at=evaluated_at,
    )
    market = market_snapshot_from_bar(bar, observed_at=evaluated_at)
    decision = evaluate_order(order, market, LIVE_PAPER_EXECUTION_PROFILE)
    _require_full_market_fill(decision, quantity=quantity)
    return FillProvenance(
        decision=decision,
        market_interval=bar.interval,
        evaluated_at=evaluated_at,
        order_type=SimulationOrderType.MARKET.value,
    )


def _require_full_market_fill(decision: FillDecision, *, quantity: Decimal) -> Decimal:
    if (
        decision.status is FillStatus.FILLED
        and decision.fill_price is not None
        and decision.fill_quantity == quantity
        and decision.remaining_quantity == Decimal(0)
    ):
        return decision.fill_price

    logger.error(
        "market kernel did not fully fill: status=%s fill_qty=%s remaining=%s reason=%s",
        decision.status,
        decision.fill_quantity,
        decision.remaining_quantity,
        decision.trace.reason,
    )
    raise TradeExecutionError("Unable to fill market order against the latest close")
