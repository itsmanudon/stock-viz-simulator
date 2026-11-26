"""A5.1 test helpers: snapshots belong to a book, so tests name it."""

from __future__ import annotations

from sqlmodel import Session

from stockviz.services.trading.books import ensure_default_portfolio


def default_book_id(session: Session, user_id: int) -> int:
    """The user's default book id, created on first use."""
    book = ensure_default_portfolio(session, user_id)
    assert book.id is not None
    return book.id
