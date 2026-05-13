"""Dividend history ingestion from yfinance.

Fetches ``Ticker.dividends`` (a pandas Series of ex_date → amount) and
upserts rows into the ``dividends`` table. Idempotent on ``(ticker, ex_date)``
— re-running updates the amount if yfinance corrects a past figure.

Call this from the ``dividends`` CLI command or from the daily scheduler.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from stockviz.models import Symbol
from stockviz.models.dividend import Dividend

logger = logging.getLogger(__name__)

DividendFetchFn = Callable[[str], list[tuple[date_type, Decimal]]]
"""(ticker) -> list of (ex_date, amount) pairs, oldest first."""


def _default_dividend_fetch(ticker: str) -> list[tuple[date_type, Decimal]]:
    import yfinance as yf

    series = yf.Ticker(ticker).dividends
    if series is None or series.empty:
        return []
    out: list[tuple[date_type, Decimal]] = []
    for ts, val in series.items():
        try:
            ex_date = date_type.fromisoformat(str(ts)[:10])
            amount = Decimal(str(val)).quantize(Decimal("0.000001"))
            out.append((ex_date, amount))
        except (InvalidOperation, AttributeError, ValueError):
            continue
    return out


def ingest_dividends_for_ticker(
    session: Session,
    ticker: str,
    *,
    fetch_fn: DividendFetchFn = _default_dividend_fetch,
) -> int:
    """Upsert all historical dividends for ``ticker``. Returns rows written."""
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        logger.warning("ingest_dividends: unknown ticker %s, skipping", ticker)
        return 0

    try:
        rows = fetch_fn(ticker)
    except Exception as exc:
        logger.warning("ingest_dividends: %s yfinance.dividends failed: %s", ticker, exc)
        return 0

    written = 0
    for ex_date, amount in rows:
        existing = session.exec(
            select(Dividend).where(Dividend.ticker == ticker, Dividend.ex_date == ex_date)
        ).first()
        if existing is None:
            session.add(Dividend(ticker=ticker, ex_date=ex_date, amount=amount))
            written += 1
        elif existing.amount != amount:
            existing.amount = amount
            written += 1

    session.commit()
    return written


def ingest_dividends_for_all(
    session: Session,
    *,
    fetch_fn: DividendFetchFn = _default_dividend_fetch,
    only: list[str] | None = None,
) -> dict[str, int]:
    """Run ``ingest_dividends_for_ticker`` for every active symbol (or ``only``)."""
    stmt = select(Symbol.ticker).where(Symbol.is_active)  # type: ignore[arg-type]
    if only:
        stmt = stmt.where(Symbol.ticker.in_(only))  # type: ignore[attr-defined]
    tickers = list(session.exec(stmt).all())

    results: dict[str, int] = {}
    for ticker in tickers:
        results[ticker] = ingest_dividends_for_ticker(session, ticker, fetch_fn=fetch_fn)
    return results
