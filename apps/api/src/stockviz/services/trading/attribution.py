"""FX return attribution for each holding (Phase 8.2).

For a holding bought in currency N and valued in base currency B, the gain in
B since entry splits exactly into three parts:

- **price:**    quantity x (close - average cost) x entry rate
- **currency:** quantity x average cost x (rate now - entry rate)
- **cross:**    quantity x (close - average cost) x (rate now - entry rate)

Average cost is the ledger's native weighted average. The entry rate is the
notional-weighted average of ``trades.fx_rate`` (B per N) over the buys of
the current holding: buys since the running quantity last reached zero.
Dividends since then are income, in B at their stored ``base_value``. A
holding in the base currency has rate 1 throughout, so all of it is price.

A reverse split leaves the running quantity above the real one, so a holding
sold out and bought again after one may mix both buys into its entry rate;
forward splits and ordinary trading do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import Portfolio, PortfolioDividend, Trade, TradeSide
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.portfolio import PortfolioValuation

ATTRIBUTION_METHOD = "price_currency_cross"
ATTRIBUTION_BASIS = (
    "gain since entry in the base currency, at the average cost and the "
    "notional-weighted entry rate of the current holding's buys"
)


@dataclass(frozen=True, slots=True)
class HoldingAttribution:
    ticker: str
    currency: str
    entry_rate: Decimal | None
    rate_now: Decimal | None
    cost_base: Decimal | None
    value_base: Decimal | None
    price_effect: Decimal | None
    currency_effect: Decimal | None
    cross_effect: Decimal | None
    income: Decimal
    reason: str | None = None


def _entry_trades(trades: list[Trade]) -> list[Trade]:
    """Buys of the current holding: those after the running quantity last hit zero."""
    running = Decimal(0)
    current: list[Trade] = []
    for trade in trades:
        if trade.side == TradeSide.BUY:
            if running <= 0:
                current = []
                running = Decimal(0)
            running += trade.quantity
            current.append(trade)
        else:
            running -= trade.quantity
    return current


def _unattributed(ticker: str, currency: str, income: Decimal, reason: str) -> HoldingAttribution:
    return HoldingAttribution(
        ticker,
        currency,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        income.quantize(Decimal("0.01")),
        reason,
    )


def attribute(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation
) -> list[HoldingAttribution]:
    assert portfolio.id is not None
    base = portfolio.base_currency or "USD"
    tickers = [p.ticker for p in valuation.positions]
    if not tickers:
        return []
    trades = session.exec(
        select(Trade)
        .where(Trade.portfolio_id == portfolio.id, col(Trade.ticker).in_(tickers))
        .order_by(col(Trade.ts), col(Trade.id))
    ).all()
    dividends = session.exec(
        select(PortfolioDividend).where(
            PortfolioDividend.portfolio_id == portfolio.id,
            col(PortfolioDividend.ticker).in_(tickers),
        )
    ).all()
    out: list[HoldingAttribution] = []
    for position in valuation.positions:
        native = position.currency
        buys = _entry_trades([t for t in trades if t.ticker == position.ticker])
        since: datetime | None = buys[0].ts if buys else None
        income = sum(
            (
                d.base_value
                for d in dividends
                if d.ticker == position.ticker and since is not None and d.ex_date >= since.date()
            ),
            Decimal(0),
        )

        if position.last_close is None:
            out.append(_unattributed(position.ticker, native, income, "no stored close"))
            continue
        if native == base:
            entry = now = Decimal(1)
        else:
            notional = sum((t.quantity * t.price for t in buys), Decimal(0))
            if not buys or notional == 0 or any(t.fx_rate is None for t in buys):
                out.append(
                    _unattributed(position.ticker, native, income, "a buy has no stored rate")
                )
                continue
            entry = sum((t.quantity * t.price * (t.fx_rate or 0) for t in buys), Decimal(0)) / (
                notional
            )
            try:
                now = fx_convert(session, Decimal(1), from_currency=native, to_currency=base)
            except LookupError:
                out.append(_unattributed(position.ticker, native, income, "no FX rate today"))
                continue
        qty, cost, close = position.quantity, position.avg_cost, position.last_close
        price = qty * (close - cost) * entry
        ccy = qty * cost * (now - entry)
        cross = qty * (close - cost) * (now - entry)
        q = Decimal("0.01")
        out.append(
            HoldingAttribution(
                ticker=position.ticker,
                currency=native,
                entry_rate=entry.quantize(Decimal("0.00000001")),
                rate_now=now.quantize(Decimal("0.00000001")),
                cost_base=(qty * cost * entry).quantize(q),
                value_base=(qty * close * now).quantize(q),
                price_effect=price.quantize(q),
                currency_effect=ccy.quantize(q),
                cross_effect=cross.quantize(q),
                income=income.quantize(q),
            )
        )
    return out
