"""Bounded daily close inputs, oldest first, without loading complete history."""

from decimal import Decimal

from sqlalchemy import func, true
from sqlmodel import Session, select

from stockviz.models import PriceBar, Symbol


def recent_closes_statement(tickers: list[str], limit: int, *, dialect: str):
    if dialect == "postgresql":
        # The existing (ticker, interval, ts) index supports one backward index
        # scan per requested symbol. The LIMIT is INSIDE the correlated scan.
        # Do not filter is_active: portfolio valuation also needs delisted names.
        recent = (
            select(PriceBar.ts, PriceBar.close)  # type: ignore[call-overload]
            .where(PriceBar.ticker == Symbol.ticker, PriceBar.interval == "1d")
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
            .over(partition_by=PriceBar.ticker, order_by=PriceBar.ts.desc())  # type: ignore[attr-defined]
            .label("rn"),
        )
        .where(PriceBar.ticker.in_(tickers), PriceBar.interval == "1d")  # type: ignore[attr-defined]
        .subquery()
    )
    return (
        select(ranked.c.ticker, ranked.c.ts, ranked.c.close)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.ticker, ranked.c.ts)
    )


def recent_closes(
    session: Session, tickers: list[str], *, limit_per_ticker: int
) -> dict[str, list[Decimal]]:
    if not tickers:
        return {}
    if limit_per_ticker < 1:
        raise ValueError("limit_per_ticker must be positive")
    rows = session.exec(
        recent_closes_statement(tickers, limit_per_ticker, dialect=session.get_bind().dialect.name)
    ).all()
    out: dict[str, list[Decimal]] = {}
    for ticker, _ts, close in rows:
        out.setdefault(ticker, []).append(close)
    return out
