"""Which book a request means (A5.1, M10.1).

A user holds several books (``portfolios`` rows). Every route that reads or
writes one goes through :func:`resolve_book`:

- no id means the user's default book, created on first use;
- another user's id, or an id that does not exist, is :class:`BookNotFound`
  (a 404, never a 403, so ids leak nothing);
- an archived book is readable; writing to it, or to an imported book, is
  :class:`BookNotWritable` (a 409).

Nothing else may find a portfolio by its user alone
(``tests/test_book_lookup_allowlist.py``).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from stockviz.models import BookKind, Portfolio
from stockviz.services.trading.buying_power import lock_user

DEFAULT_BOOK_NAME = "Default"

DEFAULT_STARTING_CASH = Decimal("100000.00")
"""Matches the v1 simulator: every new portfolio starts with $100k."""


class BookNotFound(Exception):
    """No such book for this user (404)."""

    def __init__(self, message: str = "Book not found") -> None:
        super().__init__(message)


class BookNotWritable(Exception):
    """The book is archived or imported, so nothing can trade in it (409)."""


def default_book(session: Session, user_id: int) -> Portfolio | None:
    """The user's default book, or None before first use. Never creates one."""
    return session.exec(
        select(Portfolio).where(
            col(Portfolio.user_id) == user_id,
            col(Portfolio.is_default).is_(True),
        )
    ).first()


def ensure_default_portfolio(session: Session, user_id: int) -> Portfolio:
    """Return the user's default book, creating it if needed.

    The web app calls this on the first /v1/portfolio request so users see a
    funded starting balance instead of an empty page. Idempotent — re-running
    returns the existing book.

    A brand-new book also gets a same-day NAV snapshot seeded at the starting
    cash, so return-since-inception is measured from the moment the account
    was funded rather than from whenever the nightly snapshot job first
    happened to run.
    """

    existing = default_book(session, user_id)
    if existing is not None:
        return existing

    # Serialize first-book creation on the user row. Without this, two
    # concurrent first /portfolio hits can both INSERT a default. The partial
    # unique index on (user_id) WHERE is_default makes the loser fail; the
    # lock makes it re-read instead of erroring out to the client.
    lock_user(session, user_id)
    existing = default_book(session, user_id)
    if existing is not None:
        return existing

    portfolio = Portfolio(
        user_id=user_id,
        name=_free_default_name(session, user_id),
        kind=BookKind.PAPER,
        is_default=True,
        cash_tracked=True,
        cash_balance=DEFAULT_STARTING_CASH,
        opening_nav=DEFAULT_STARTING_CASH,
    )
    session.add(portfolio)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = default_book(session, user_id)
        if existing is None:
            raise
        return existing
    session.refresh(portfolio)
    seed_opening_snapshot(session, portfolio=portfolio)
    return portfolio


def _free_default_name(session: Session, user_id: int) -> str:
    """``Default``, or ``Default 2`` and so on if the user already named a book so."""
    taken = {
        name.lower()
        for name in session.exec(
            select(Portfolio.name).where(col(Portfolio.user_id) == user_id)
        ).all()
    }
    name, n = DEFAULT_BOOK_NAME, 2
    while name.lower() in taken:
        name, n = f"{DEFAULT_BOOK_NAME} {n}", n + 1
    return name


def seed_opening_snapshot(session: Session, *, portfolio: Portfolio) -> None:
    """Write the day-zero NAV snapshot for a freshly created book. Commits.

    Imported lazily: ``services.trading.snapshots`` imports ``portfolio``,
    which imports the execute module, so a module-level import would cycle.
    """
    from stockviz._time import utcnow
    from stockviz.models import PortfolioSnapshot

    assert portfolio.id is not None
    today = utcnow().date()
    existing = session.exec(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.date == today,
        )
    ).first()
    if existing is not None:
        return
    session.add(
        PortfolioSnapshot(
            user_id=portfolio.user_id,
            portfolio_id=portfolio.id,
            date=today,
            nav=portfolio.opening_nav,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # The portfolio page fans out several /v1 calls in Promise.all; two of
        # them can pass the SELECT above and one INSERT then hits
        # uq_portfolio_snapshots_portfolio_date. The other request already
        # wrote the row — treat that as success.
        session.rollback()


def require_writable(portfolio: Portfolio) -> Portfolio:
    """Raise :class:`BookNotWritable` unless trades may land in ``portfolio``."""
    if portfolio.archived_at is not None:
        raise BookNotWritable(
            f"Book {portfolio.name!r} is archived. Unarchive it to trade in it again."
        )
    if portfolio.kind != BookKind.PAPER:
        raise BookNotWritable(
            f"Book {portfolio.name!r} is an imported book: it holds a broker's trades "
            "and takes no paper orders."
        )
    return portfolio


def resolve_book(
    session: Session, user_id: int, book_id: int | None = None, *, write: bool = False
) -> Portfolio:
    """The user's book ``book_id``, or the default book when it is None.

    ``write=True`` also refuses an archived or imported book
    (:class:`BookNotWritable`). Another user's book is :class:`BookNotFound`.
    """
    if book_id is None:
        portfolio = ensure_default_portfolio(session, user_id)
    else:
        found = session.get(Portfolio, book_id)
        if found is None or found.user_id != user_id:
            raise BookNotFound()
        portfolio = found
    if write:
        require_writable(portfolio)
    return portfolio


def owned_book(session: Session, user_id: int, portfolio_id: int | None) -> Portfolio | None:
    """The book a row (an order, an option) belongs to, if it is the user's."""
    if portfolio_id is None:
        return None
    found = session.get(Portfolio, portfolio_id)
    if found is None or found.user_id != user_id:
        return None
    return found


def user_books(session: Session, user_id: int) -> list[Portfolio]:
    """Every book the user holds, default first, then by id."""
    return list(
        session.exec(
            select(Portfolio)
            .where(col(Portfolio.user_id) == user_id)
            .order_by(col(Portfolio.is_default).desc(), col(Portfolio.id))
        ).all()
    )
