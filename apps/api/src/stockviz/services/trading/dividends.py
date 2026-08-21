"""Portfolio dividend crediting.

``credit_due_dividends`` finds every (portfolio, ticker) pair where:
  1. The portfolio holds a non-zero position in ``ticker``.
  2. The ``dividends`` table has a row for ``(ticker, credit_date)``.
  3. No ``portfolio_dividends`` row already exists for that triplet.

When all three hold it credits ``position.quantity * dividend.amount`` to
the portfolio's cash balance and writes the audit row. The unique constraint
on ``portfolio_dividends`` makes the whole operation idempotent even if the
scheduler fires twice on the same day.

Dividends are declared in the symbol's **native** currency, but cash is always
USD — so the credit converts at the FX rate for the ex-date, exactly like a
trade fill does. A symbol whose currency has no rate is skipped rather than
credited at 1:1, which would silently inflate the balance.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, Symbol
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.services.trading.fx import latest_rate

logger = logging.getLogger(__name__)

_MICROS = Decimal("0.000001")


def credit_due_dividends(session: Session, *, credit_date: date_type) -> int:
    """Credit all dividends whose ex_date == ``credit_date`` to eligible portfolios.

    Returns the number of portfolio credit events written.
    """
    due = list(session.exec(select(Dividend).where(Dividend.ex_date == credit_date)))
    if not due:
        return 0

    written = 0
    for div in due:
        symbol = session.get(Symbol, div.ticker)
        currency = (symbol.currency if symbol else None) or "USD"
        try:
            fx_rate = latest_rate(session, currency, on_or_before=credit_date)
        except LookupError:
            logger.warning(
                "dividend_credit: no %s FX rate on-or-before %s — skipping %s",
                currency,
                credit_date,
                div.ticker,
            )
            continue

        positions = list(
            session.exec(
                select(Position, Portfolio)
                .where(Position.ticker == div.ticker)  # type: ignore[arg-type]
                .join(Portfolio, Portfolio.id == Position.portfolio_id)  # type: ignore[arg-type]
                .where(Position.quantity > 0)
            )
        )
        for pos, portfolio in positions:
            already = session.exec(
                select(PortfolioDividend.id).where(
                    PortfolioDividend.portfolio_id == portfolio.id,
                    PortfolioDividend.ticker == div.ticker,
                    PortfolioDividend.ex_date == credit_date,
                )
            ).first()
            if already is not None:
                continue

            native_amount = pos.quantity * div.amount
            credit_amount = (native_amount * fx_rate).quantize(_MICROS)
            portfolio.cash_balance = (portfolio.cash_balance + credit_amount).quantize(_MICROS)
            session.add(portfolio)
            session.add(
                PortfolioDividend(
                    portfolio_id=portfolio.id,  # type: ignore[arg-type]
                    ticker=div.ticker,
                    ex_date=credit_date,
                    amount_credited=credit_amount,
                )
            )
            try:
                session.commit()
                written += 1
                logger.info(
                    "dividend_credit: portfolio %s +%s USD from %s (%s, %s @ %s)",
                    portfolio.id,
                    credit_amount,
                    div.ticker,
                    credit_date,
                    currency,
                    fx_rate,
                )
            except IntegrityError:
                session.rollback()

    return written
