"""Portfolio dividend crediting.

``credit_due_dividends`` credits every dividend whose ex-date is on or before
the run date and that a portfolio has not been paid yet (audit LG-12, #66):

1. **Catch-up.** Every uncredited ex-date up to the run date, not only today's,
   so a night the job did not run, or an ex-date that lacked an FX rate, is
   paid on the next successful run. Only ex-dates after the day the portfolio
   opened count: it cannot have held anything before it existed.
2. **Entitlement.** The holding at the close before the ex-date, not at job
   time: the current position with every trade dated on or after the
   ex-date (New York date) undone. A same-day buyer is not paid; a holder who
   sold on or after the ex-date is.

``portfolio_dividends`` is unique on ``(portfolio, ticker, ex_date)``, so a
second run, or two runs at once, never pays twice.

Dividends are declared in the symbol's **native** currency, but cash is always
USD — so the credit converts at the FX rate for the ex-date, exactly like a
trade fill does. A symbol whose currency has no rate is skipped, and paid by a
later run once a rate exists, rather than credited at 1:1.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from stockviz.models import Portfolio, Position, Symbol, Trade
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.portfolio import TradeSide
from stockviz.services.ingest.bar_semantics import NEW_YORK
from stockviz.services.instruments import instrument_of, instruments_of
from stockviz.services.trading.buying_power import lock_portfolio
from stockviz.services.trading.fx import latest_rate

logger = logging.getLogger(__name__)

_MICROS = Decimal("0.000001")


def _ny_date(ts: datetime) -> date_type:
    """New York calendar date of a naive-UTC timestamp."""
    return ts.replace(tzinfo=UTC).astimezone(NEW_YORK).date()


def _holding_before(
    current: Decimal, trades: list[tuple[date_type, Decimal]], ex_date: date_type
) -> Decimal:
    """Quantity held at the close before ``ex_date``: undo trades dated on or after it."""
    return current - sum((q for day, q in trades if day >= ex_date), Decimal(0))


def credit_due_dividends(session: Session, *, credit_date: date_type) -> int:
    """Credit every uncredited dividend with an ex-date on or before ``credit_date``.

    Returns the number of portfolio credit events written.
    """
    # Every (portfolio, ticker) that holds the ticker now or has traded it.
    current: dict[tuple[int, str], Decimal] = {}
    for pos in session.exec(select(Position).where(Position.quantity > 0)):
        current[(pos.portfolio_id, pos.ticker)] = pos.quantity
    trades: dict[tuple[int, str], list[tuple[date_type, Decimal]]] = {}
    for trade in session.exec(select(Trade)):
        signed = trade.quantity if trade.side == TradeSide.BUY else -trade.quantity
        trades.setdefault((trade.portfolio_id, trade.ticker), []).append(
            (_ny_date(trade.ts), signed)
        )
    pairs = set(current) | set(trades)
    if not pairs:
        return 0

    opened = {
        p.id: _ny_date(p.created_at)
        for p in session.exec(
            select(Portfolio).where(col(Portfolio.id).in_({pid for pid, _ in pairs}))
        )
    }
    tickers = {ticker for _, ticker in pairs}
    earliest = min(opened.values(), default=credit_date)
    due = list(
        session.exec(
            select(Dividend)
            .where(
                col(Dividend.instrument_id).in_(instruments_of(tickers)),
                Dividend.ex_date <= credit_date,
                Dividend.ex_date > earliest,
            )
            .order_by(col(Dividend.ex_date))
        )
    )
    if not due:
        return 0
    paid = {
        (row.portfolio_id, row.ticker, row.ex_date)
        for row in session.exec(
            select(PortfolioDividend).where(
                col(PortfolioDividend.instrument_id).in_(instruments_of(tickers))
            )
        )
    }

    written = 0
    for div in due:
        symbol = session.get(Symbol, div.ticker)
        currency = (symbol.currency if symbol else None) or "USD"
        try:
            fx_rate = latest_rate(session, currency, on_or_before=div.ex_date)
        except LookupError:
            logger.warning(
                "dividend_credit: no %s FX rate on-or-before %s — skipping %s until a later run",
                currency,
                div.ex_date,
                div.ticker,
            )
            continue

        for portfolio_id, ticker in sorted(pairs):
            if ticker != div.ticker or (portfolio_id, ticker, div.ex_date) in paid:
                continue
            if opened.get(portfolio_id, div.ex_date) >= div.ex_date:
                continue
            quantity = _holding_before(
                current.get((portfolio_id, ticker), Decimal(0)),
                trades.get((portfolio_id, ticker), []),
                div.ex_date,
            )
            if quantity <= 0:
                continue

            portfolio = lock_portfolio(session, portfolio_id)
            # Re-check under the lock: a concurrent run may have paid it.
            already = session.exec(
                select(PortfolioDividend.id).where(
                    PortfolioDividend.portfolio_id == portfolio_id,
                    PortfolioDividend.instrument_id == instrument_of(ticker),
                    PortfolioDividend.ex_date == div.ex_date,
                )
            ).first()
            if already is not None:
                session.commit()
                continue

            credit_amount = (quantity * div.amount * fx_rate).quantize(_MICROS)
            portfolio.cash_balance = (portfolio.cash_balance + credit_amount).quantize(_MICROS)
            session.add(portfolio)
            session.add(
                PortfolioDividend(
                    portfolio_id=portfolio_id,
                    ticker=ticker,
                    ex_date=div.ex_date,
                    amount_credited=credit_amount,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                continue
            written += 1
            paid.add((portfolio_id, ticker, div.ex_date))
            logger.info(
                "dividend_credit: portfolio %s +%s USD from %s (ex %s, %s shares, %s @ %s)",
                portfolio_id,
                credit_amount,
                ticker,
                div.ex_date,
                quantity,
                currency,
                fx_rate,
            )

    return written
