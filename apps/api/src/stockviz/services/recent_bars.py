"""Bounded daily close inputs, oldest first, without loading complete history."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, true
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.instruments import instrument_of, instruments_of


def recent_closes_statement(tickers: list[str], limit: int, *, dialect: str):
    if dialect == "postgresql":
        # The (instrument_id, interval, ts) index supports one backward index
        # scan per requested symbol. The LIMIT is INSIDE the correlated scan.
        # Do not filter is_active: portfolio valuation also needs delisted names.
        recent = (
            select(PriceBar.ts, PriceBar.close)  # type: ignore[call-overload]
            .where(
                col(PriceBar.instrument_id) == instrument_of(Symbol.ticker),
                PriceBar.interval == "1d",
            )
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(limit)
            .correlate(Symbol)
            .lateral()
        )
        return (
            select(Symbol.ticker, recent.c.ts, recent.c.close)
            .select_from(Symbol)
            .join(recent, true())
            .where(Symbol.ticker.in_(tickers))  # type: ignore[attr-defined]
            .order_by(Symbol.ticker, recent.c.ts)
        )

    # SQLite test/development compatibility; SQLite has no LATERAL support.
    ranked = (
        select(
            PriceBar.ticker,
            PriceBar.ts,
            PriceBar.close,  # type: ignore[arg-type]
            func.row_number()
            .over(partition_by=PriceBar.instrument_id, order_by=PriceBar.ts.desc())  # type: ignore[attr-defined]
            .label("rn"),
        )
        .where(
            col(PriceBar.instrument_id).in_(instruments_of(tickers)),
            PriceBar.interval == "1d",
        )
        .subquery()
    )
    return (
        select(ranked.c.ticker, ranked.c.ts, ranked.c.close)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.ticker, ranked.c.ts)
    )


def recent_bars(
    session: Session, tickers: list[str], *, limit_per_ticker: int
) -> dict[str, list[tuple[datetime, Decimal]]]:
    """Most recent ``(ts, close)`` pairs per ticker, oldest first.

    Callers that show a price also need the bar it came from, so a page can
    say which close it is (web UI audit T1).
    """
    if not tickers:
        return {}
    if limit_per_ticker < 1:
        raise ValueError("limit_per_ticker must be positive")
    rows = session.exec(
        recent_closes_statement(tickers, limit_per_ticker, dialect=session.get_bind().dialect.name)
    ).all()
    out: dict[str, list[tuple[datetime, Decimal]]] = {}
    for ticker, ts, close in rows:
        out.setdefault(ticker, []).append((ts, close))
    return out


def recent_closes(
    session: Session, tickers: list[str], *, limit_per_ticker: int
) -> dict[str, list[Decimal]]:
    return {
        ticker: [close for _ts, close in bars]
        for ticker, bars in recent_bars(session, tickers, limit_per_ticker=limit_per_ticker).items()
    }
