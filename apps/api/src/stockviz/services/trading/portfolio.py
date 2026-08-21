"""Portfolio valuation.

``compute_portfolio`` snapshots a user's default portfolio: positions priced
at the latest close in their native currency, then converted into a chosen
display currency. Cash is held in USD; ``cash_balance`` on the returned
valuation is already in the display currency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
)
from stockviz.models.option import CONTRACT_MULTIPLIER
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.fx import latest_rate


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    ticker: str
    name: str
    quantity: Decimal
    # Native currency the symbol trades in (e.g. EUR for SAP.DE).
    currency: str
    # Per-share cost basis in native currency.
    avg_cost: Decimal
    # Latest close in native currency. None when there's no bar yet.
    last_close: Decimal | None
    # Holding's market value in native currency.
    market_value_native: Decimal
    # Unrealized P&L in native currency.
    unrealized_pl_native: Decimal
    # Same numbers converted to the user's display currency.
    market_value: Decimal
    unrealized_pl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioOptionPosition:
    """An open option contract, marked to its Black-Scholes value."""

    option_id: int
    ticker: str
    option_type: str
    strike: Decimal
    expiry: date_type
    quantity: int  # contracts
    currency: str
    premium_paid: Decimal
    # Theoretical value of the whole holding (per-share value x 100 x contracts),
    # in the underlying's native currency, then in the display currency.
    market_value_native: Decimal
    market_value: Decimal
    unrealized_pl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    portfolio_id: int
    # Currency every aggregate (cash, market_value, totals) is denominated in.
    display_currency: str
    cash_balance: Decimal
    positions: list[PortfolioPosition] = field(default_factory=list)
    option_positions: list[PortfolioOptionPosition] = field(default_factory=list)
    # Equity market value only (kept as-is for existing callers).
    market_value: Decimal = Decimal(0)
    # Mark-to-model value of open option contracts.
    options_market_value: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    total_cost_basis: Decimal = Decimal(0)
    unrealized_pl: Decimal = Decimal(0)


def latest_close_map(session: Session, tickers: list[str]) -> dict[str, Decimal]:
    """Per-ticker latest ``1d`` close, in the symbol's native currency.

    One query for the whole set instead of one per ticker: rank each ticker's
    bars by ``ts`` descending and keep the first. This is the hot path for
    every portfolio read, so the N+1 version showed up directly in page
    latency once a portfolio held more than a handful of names.
    """
    if not tickers:
        return {}

    ranked = (
        select(
            PriceBar.ticker,
            PriceBar.close,  # type: ignore[arg-type]
            func.row_number()
            .over(
                partition_by=PriceBar.ticker,  # type: ignore[arg-type]
                order_by=PriceBar.ts.desc(),  # type: ignore[attr-defined]
            )
            .label("rn"),
        )
        .where(
            PriceBar.ticker.in_(tickers),  # type: ignore[attr-defined]
            PriceBar.interval == "1d",
        )
        .subquery()
    )
    rows = session.exec(select(ranked.c.ticker, ranked.c.close).where(ranked.c.rn == 1)).all()  # type: ignore[call-overload]
    return dict(rows)


# Back-compat alias — the private name predates the public one.
_latest_close_map = latest_close_map


def compute_portfolio(
    session: Session,
    portfolio: Portfolio,
    *,
    display_currency: str = "USD",
) -> PortfolioValuation:
    """Snapshot the portfolio with latest-close pricing in ``display_currency``.

    The cash balance is stored in USD; we convert it to the display currency
    before returning. Per-position values are exposed in both native and
    display currency so the UI can show either side.

    Missing FX rates are treated as "skip conversion" for that one position
    (the native amount is used as-is) — a defensive choice so the page still
    renders if the FX refresh is briefly behind.
    """

    assert portfolio.id is not None

    rows = list(
        session.exec(
            select(Position, Symbol)
            .where(Position.portfolio_id == portfolio.id)  # type: ignore[arg-type]
            .join(Symbol, Symbol.ticker == Position.ticker)  # type: ignore[arg-type]
        )
    )
    tickers = [pos.ticker for pos, _ in rows]
    close_by_ticker = latest_close_map(session, tickers)

    def _to_display(amount: Decimal, from_ccy: str) -> Decimal:
        if from_ccy == display_currency:
            return amount
        try:
            return fx_convert(session, amount, from_currency=from_ccy, to_currency=display_currency)
        except LookupError:
            return amount

    positions: list[PortfolioPosition] = []
    market_value_display = Decimal(0)
    cost_basis_display = Decimal(0)
    for pos, sym in rows:
        native_ccy = sym.currency or "USD"
        last = close_by_ticker.get(pos.ticker)
        mv_native = (last * pos.quantity) if last is not None else Decimal(0)
        cost_native = pos.avg_cost * pos.quantity
        pl_native = mv_native - cost_native

        mv_display = _to_display(mv_native, native_ccy)
        cost_display = _to_display(cost_native, native_ccy)
        pl_display = mv_display - cost_display

        positions.append(
            PortfolioPosition(
                ticker=pos.ticker,
                name=sym.name,
                quantity=pos.quantity,
                currency=native_ccy,
                avg_cost=pos.avg_cost,
                last_close=last,
                market_value_native=mv_native,
                unrealized_pl_native=pl_native,
                market_value=mv_display,
                unrealized_pl=pl_display,
            )
        )
        market_value_display += mv_display
        cost_basis_display += cost_display

    # Cash is USD-base — convert to display currency.
    if display_currency == "USD":
        cash_display = portfolio.cash_balance
    else:
        try:
            usd_per_display = latest_rate(session, display_currency)
            cash_display = (
                portfolio.cash_balance / usd_per_display
                if usd_per_display != Decimal(0)
                else portfolio.cash_balance
            )
        except LookupError:
            cash_display = portfolio.cash_balance

    option_positions, options_value_display = _value_open_options(
        session, portfolio_id=portfolio.id, to_display=_to_display
    )

    total_value = market_value_display + options_value_display + cash_display
    return PortfolioValuation(
        portfolio_id=portfolio.id,
        display_currency=display_currency,
        cash_balance=cash_display,
        positions=positions,
        option_positions=option_positions,
        market_value=market_value_display,
        options_market_value=options_value_display,
        total_value=total_value,
        total_cost_basis=cost_basis_display,
        unrealized_pl=market_value_display - cost_basis_display,
    )


def _value_open_options(
    session: Session,
    *,
    portfolio_id: int,
    to_display: Callable[[Decimal, str], Decimal],
) -> tuple[list[PortfolioOptionPosition], Decimal]:
    """Mark every open option contract to its Black-Scholes value.

    Without this the premium leaves the cash bucket at open and nothing
    replaces it, so NAV understates a live options book by exactly the amount
    the user has at risk. A contract we can't price (no bars for the
    underlying) contributes zero rather than blocking the whole page.
    """
    from stockviz.services.options.trade import NoOptionMarketData, value_option

    rows = list(
        session.exec(
            select(OptionsPosition, Symbol)
            .where(
                OptionsPosition.portfolio_id == portfolio_id,  # type: ignore[arg-type]
                OptionsPosition.status == OptionStatus.OPEN,  # type: ignore[arg-type]
            )
            .join(Symbol, Symbol.ticker == OptionsPosition.ticker)  # type: ignore[arg-type]
        )
    )

    out: list[PortfolioOptionPosition] = []
    total_display = Decimal(0)
    for opt, sym in rows:
        native_ccy = sym.currency or "USD"
        try:
            priced = value_option(session, opt)
            per_share = Decimal(str(priced.value))
        except NoOptionMarketData:
            per_share = Decimal(0)

        mv_native = (per_share * CONTRACT_MULTIPLIER * opt.quantity).quantize(Decimal("0.000001"))
        if mv_native < 0:
            mv_native = Decimal(0)
        mv_display = to_display(mv_native, native_ccy)
        # premium_paid is already USD (cash is USD), so compare in USD terms.
        premium_display = to_display(opt.premium_paid, "USD")

        out.append(
            PortfolioOptionPosition(
                option_id=opt.id,  # type: ignore[arg-type]
                ticker=opt.ticker,
                option_type=opt.option_type.value,
                strike=opt.strike,
                expiry=opt.expiry,
                quantity=opt.quantity,
                currency=native_ccy,
                premium_paid=opt.premium_paid,
                market_value_native=mv_native,
                market_value=mv_display,
                unrealized_pl=mv_display - premium_display,
            )
        )
        total_display += mv_display

    return out, total_display
