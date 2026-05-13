"""Portfolio dividend crediting.

``credit_due_dividends`` finds every (portfolio, ticker) pair where:
  1. The portfolio holds a non-zero position in ``ticker``.
  2. The ``dividends`` table has a row for ``(ticker, credit_date)``.
  3. No ``portfolio_dividends`` row already exists for that triplet.

When all three hold it credits ``position.quantity * dividend.amount`` to
the portfolio's cash balance and writes the audit row. The unique constraint
on ``portfolio_dividends`` makes the whole operation idempotent even if the
scheduler fires twice on the same day.
"""

from __future__ import annotations

import logging
from datetime import date as date_type

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz.models import Portfolio, Position
from stockviz.models.dividend import Dividend, PortfolioDividend

logger = logging.getLogger(__name__)


def credit_due_dividends(session: Session, *, credit_date: date_type) -> int:
    """Credit all dividends whose ex_date == ``credit_date`` to eligible portfolios.

    Returns the number of portfolio credit events written.
    """
    due = list(
        session.exec(select(Dividend).where(Dividend.ex_date == credit_date))
    )
    if not due:
        return 0

    written = 0
    for div in due:
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
                select(PortfolioDividend).where(
                    PortfolioDividend.portfolio_id == portfolio.id,
                    PortfolioDividend.ticker == div.ticker,
                    PortfolioDividend.ex_date == credit_date,
                )
            ).first()
            if already is not None:
                continue

            credit_amount = (pos.quantity * div.amount).quantize(div.amount)
            portfolio.cash_balance += credit_amount
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
                    "dividend_credit: portfolio %s +%s from %s (%s)",
                    portfolio.id,
                    credit_amount,
                    div.ticker,
                    credit_date,
                )
            except IntegrityError:
                session.rollback()

    return written
