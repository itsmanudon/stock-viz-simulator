"""Book create, rename, archive, default and delete (A5.1, M10.1).

Rules (``docs/a5-design-note.md``, "Books"; question 1's recommendations):

- At most ``MAX_BOOKS_PER_USER`` (20) books a user, archived ones included.
- Names are 1-60 characters, unique per user ignoring case (409).
- A paper book starts with ``STARTING_CASH`` in its base currency
  ($100,000 or ₹1 crore) and a day-zero snapshot. An imported book (A5.3
  fills it) is holdings-only: ``cash_tracked`` false, cash 0.
- The holder is a kind (``self``, ``family``, ``huf``) and a free-text label;
  a label shaped like a PAN is refused: no PAN is stored.
- Exactly one default per user, always a paper book that is not archived.
  Making another book the default moves the flag in one transaction.
- The default book can't be archived; a book with pending orders can't be
  archived until they are cancelled (settlement would trade in it).
- Delete refuses the default book (and so the last one) and any book that
  is neither empty nor archived. It removes everything in the book: these
  are the user's records, so the delete is hard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import (
    MAX_BOOKS_PER_USER,
    Alert,
    BookKind,
    CashBalance,
    CorporateActionApplication,
    FxConversion,
    HolderKind,
    OptionsPosition,
    OptionStrategy,
    PendingOrder,
    Portfolio,
    PortfolioDividend,
    PortfolioSnapshot,
    PortfolioTradeActivity,
    Position,
    SimulatedExecution,
    Trade,
)
from stockviz.models.order import OrderStatus
from stockviz.models.portfolio import BOOK_NAME_MAX, HOLDER_LABEL_MAX
from stockviz.models.risk_limit import RiskLimit
from stockviz.services.trading.account import STARTING_CASH, activity
from stockviz.services.trading.books import (
    BookNotFound,
    ensure_default_portfolio,
    resolve_book,
    seed_opening_snapshot,
    user_books,
)
from stockviz.services.trading.buying_power import lock_portfolio, lock_user

BROKERS = ("zerodha",)

# Five letters, four digits, a letter: the shape of an Indian PAN.
_PAN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]", re.IGNORECASE)


class BookError(Exception):
    """A request the rules refuse (the router maps the subclass to a status)."""


class BookConflict(BookError):
    """409: the cap, a taken name, the default's rules, pending orders."""


class BookInvalid(BookError):
    """422: a value the rules don't accept."""


@dataclass(frozen=True, slots=True)
class BookView:
    book: Portfolio
    activity: list[str]


def clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not 1 <= len(cleaned) <= BOOK_NAME_MAX:
        raise BookInvalid(f"A book name is 1 to {BOOK_NAME_MAX} characters")
    return cleaned


def clean_holder_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = " ".join(label.split())
    if not cleaned:
        return None
    if len(cleaned) > HOLDER_LABEL_MAX:
        raise BookInvalid(f"A holder label is at most {HOLDER_LABEL_MAX} characters")
    if _PAN.search(cleaned):
        raise BookInvalid(
            "That label looks like a PAN. Books keep a name only (self, a family "
            "member, an HUF); no PAN is stored."
        )
    return cleaned


def _name_taken(session: Session, user_id: int, name: str, *, except_id: int | None) -> bool:
    stmt = select(Portfolio.id).where(
        col(Portfolio.user_id) == user_id, func.lower(Portfolio.name) == name.lower()
    )
    if except_id is not None:
        stmt = stmt.where(col(Portfolio.id) != except_id)
    return session.exec(stmt).first() is not None


def list_books(session: Session, user_id: int) -> list[BookView]:
    """Every book, default first. Creates the default book on first use."""
    ensure_default_portfolio(session, user_id)
    return [BookView(book, activity(session, book)) for book in user_books(session, user_id)]


def view(session: Session, book: Portfolio) -> BookView:
    return BookView(book, activity(session, book))


def create_book(
    session: Session,
    *,
    user_id: int,
    name: str,
    kind: BookKind = BookKind.PAPER,
    base_currency: str = "USD",
    holder_kind: HolderKind = HolderKind.SELF,
    holder_label: str | None = None,
    broker: str | None = None,
) -> Portfolio:
    """Create a book. Commits. The user's default book exists first."""
    name = clean_name(name)
    holder_label = clean_holder_label(holder_label)
    base_currency = base_currency.upper()
    if base_currency not in STARTING_CASH:
        raise BookInvalid(f"Base currency must be one of {', '.join(sorted(STARTING_CASH))}")
    if kind == BookKind.PAPER and broker is not None:
        raise BookInvalid("A paper book has no broker")
    if kind == BookKind.IMPORTED:
        broker = broker or "zerodha"
        if broker not in BROKERS:
            raise BookInvalid(f"Broker must be one of {', '.join(BROKERS)}")

    ensure_default_portfolio(session, user_id)
    lock_user(session, user_id)
    count = session.exec(
        select(func.count()).select_from(Portfolio).where(col(Portfolio.user_id) == user_id)
    ).one()
    if count >= MAX_BOOKS_PER_USER:
        session.rollback()
        raise BookConflict(
            f"You already have {MAX_BOOKS_PER_USER} books, the most allowed. "
            "Delete one before adding another."
        )
    if _name_taken(session, user_id, name, except_id=None):
        session.rollback()
        raise BookConflict(f"You already have a book named {name!r}")

    paper = kind == BookKind.PAPER
    start = STARTING_CASH[base_currency] if paper else Decimal(0)
    book = Portfolio(
        user_id=user_id,
        name=name,
        kind=kind,
        is_default=False,
        cash_tracked=paper,
        broker=broker,
        holder_kind=holder_kind,
        holder_label=holder_label,
        base_currency=base_currency,
        cash_balance=start,
        opening_nav=start,
    )
    session.add(book)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BookConflict(f"You already have a book named {name!r}") from exc
    session.refresh(book)
    if paper:
        seed_opening_snapshot(session, portfolio=book)
        session.refresh(book)
    return book


_UNSET = object()


def update_book(
    session: Session,
    *,
    user_id: int,
    book_id: int,
    name: str | None = None,
    holder_kind: HolderKind | None = None,
    holder_label: object = _UNSET,
    archived: bool | None = None,
    make_default: bool = False,
) -> Portfolio:
    """Rename, relabel, archive or unarchive a book, or make it the default. Commits."""
    book = resolve_book(session, user_id, book_id)
    assert book.id is not None
    lock_user(session, user_id)
    book = lock_portfolio(session, book.id)

    if name is not None:
        cleaned = clean_name(name)
        if _name_taken(session, user_id, cleaned, except_id=book.id):
            session.rollback()
            raise BookConflict(f"You already have a book named {cleaned!r}")
        book.name = cleaned
    if holder_kind is not None:
        book.holder_kind = holder_kind
    if holder_label is not _UNSET:
        book.holder_label = clean_holder_label(holder_label)  # type: ignore[arg-type]

    if archived is True and (book.is_default or make_default):
        session.rollback()
        raise BookConflict(
            "The default book can't be archived. Make another book the default first."
        )
    if archived is True and book.archived_at is None:
        pending = session.exec(
            select(func.count())
            .select_from(PendingOrder)
            .where(
                col(PendingOrder.portfolio_id) == book.id,
                col(PendingOrder.status) == OrderStatus.PENDING,
            )
        ).one()
        if pending:
            session.rollback()
            raise BookConflict(
                f"This book has {pending} pending order(s). Cancel them before archiving it."
            )
        book.archived_at = utcnow()
    elif archived is False:
        book.archived_at = None

    if make_default and not book.is_default:
        if book.kind != BookKind.PAPER:
            session.rollback()
            raise BookConflict("Only a paper book can be the default.")
        if book.archived_at is not None:
            session.rollback()
            raise BookConflict("An archived book can't be the default. Unarchive it first.")
        # Clear the old default first: the partial unique index allows one.
        session.exec(
            update(Portfolio)
            .where(col(Portfolio.user_id) == user_id, col(Portfolio.is_default).is_(True))
            .values(is_default=False)
        )  # type: ignore[call-overload]
        session.flush()
        book.is_default = True
    session.add(book)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BookConflict("That change conflicts with another book; try again.") from exc
    session.refresh(book)
    return book


def delete_book(session: Session, *, user_id: int, book_id: int) -> None:
    """Delete a book and everything in it. Commits.

    Refuses the default book (so the last book too), and a book that has
    activity unless it is archived first (the web asks twice).
    """
    book = resolve_book(session, user_id, book_id)
    assert book.id is not None
    lock_user(session, user_id)
    book = lock_portfolio(session, book.id)
    if book.is_default:
        session.rollback()
        raise BookConflict(
            "The default book can't be deleted. Make another book the default first."
        )
    remaining = session.exec(
        select(func.count()).select_from(Portfolio).where(col(Portfolio.user_id) == user_id)
    ).one()
    if remaining <= 1:
        session.rollback()
        raise BookConflict("Your last book can't be deleted.")
    done = activity(session, book)
    if done and book.archived_at is None:
        session.rollback()
        raise BookConflict(
            f"This book has {', '.join(done)}. Archive it before deleting it, "
            "or delete only an empty book."
        )
    assert book.id is not None
    _delete_contents(session, book.id)
    session.delete(book)
    session.commit()


def _delete_contents(session: Session, pid: int) -> None:
    """Every row that belongs to book ``pid``, children first."""
    trade_ids = select(Trade.id).where(col(Trade.portfolio_id) == pid)
    session.exec(delete(SimulatedExecution).where(col(SimulatedExecution.trade_id).in_(trade_ids)))  # type: ignore[call-overload]
    session.exec(delete(FxConversion).where(col(FxConversion.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(Trade).where(col(Trade.portfolio_id) == pid))  # type: ignore[call-overload]
    # A5.3: an imported book's fills and import batches (after their trades).
    from stockviz.models.broker_import import BrokerFill, ImportBatch

    session.exec(delete(BrokerFill).where(col(BrokerFill.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(ImportBatch).where(col(ImportBatch.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(Position).where(col(Position.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(PendingOrder).where(col(PendingOrder.portfolio_id) == pid))  # type: ignore[call-overload]
    from stockviz.models.trade_plan import TradePlan

    session.exec(delete(TradePlan).where(col(TradePlan.portfolio_id) == pid))  # type: ignore[call-overload]
    # Legs point at each other (covering_leg_id) and at their strategy.
    session.exec(
        update(OptionsPosition)
        .where(col(OptionsPosition.portfolio_id) == pid)
        .values(covering_leg_id=None, strategy_id=None)
    )  # type: ignore[call-overload]
    session.exec(delete(OptionsPosition).where(col(OptionsPosition.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(OptionStrategy).where(col(OptionStrategy.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(PortfolioDividend).where(col(PortfolioDividend.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(CashBalance).where(col(CashBalance.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(delete(RiskLimit).where(col(RiskLimit.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(
        delete(PortfolioTradeActivity).where(col(PortfolioTradeActivity.portfolio_id) == pid)
    )  # type: ignore[call-overload]
    session.exec(delete(PortfolioSnapshot).where(col(PortfolioSnapshot.portfolio_id) == pid))  # type: ignore[call-overload]
    session.exec(
        delete(CorporateActionApplication).where(
            col(CorporateActionApplication.portfolio_id) == pid
        )
    )  # type: ignore[call-overload]
    # Portfolio rules on this book (the FK cascades on PostgreSQL too).
    session.exec(delete(Alert).where(col(Alert.portfolio_id) == pid))  # type: ignore[call-overload]
    session.flush()


__all__ = [
    "BROKERS",
    "BookConflict",
    "BookError",
    "BookInvalid",
    "BookNotFound",
    "BookView",
    "create_book",
    "delete_book",
    "list_books",
    "update_book",
    "view",
]
