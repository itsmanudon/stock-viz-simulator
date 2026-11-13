"""Seed symbols in tests (Phase 4.6b).

A row in a ticker table needs its symbol: the write resolves the ticker to
the symbol's instrument, and the instrument is the key. Postgres always
refused a bar for an unknown ticker (``symbols.ticker`` foreign key); SQLite
did not enforce it, so some tests wrote bars with no symbol. They seed one now.
"""

from __future__ import annotations

from sqlmodel import Session

from stockviz.models import Symbol


def seed_symbols(session: Session, *tickers: str, currency: str = "USD") -> None:
    for ticker in tickers:
        if session.get(Symbol, ticker) is None:
            session.add(Symbol(ticker=ticker, name=ticker, currency=currency))
    session.commit()
