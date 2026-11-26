"""Daily portfolio NAV snapshots.

Computes total_value (cash + market value of all positions priced at the most
recent EOD close) for each book and upserts it into ``portfolio_snapshots``.
Idempotent on ``(portfolio_id, date)`` (A5.1) so the scheduler / CLI can
re-run safely.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio, PortfolioSnapshot
from stockviz.services.trading.portfolio import compute_portfolio

logger = logging.getLogger(__name__)


class IncompleteValuation(ValueError):
    """The valuation left something out, so its NAV is not stored (LG-13)."""


def upsert_book_snapshot(
    session: Session, *, portfolio: Portfolio, snapshot_date: date_type
) -> PortfolioSnapshot:
    """Compute today's NAV for one book and write/refresh its row (A5.1: per book).

    NAV uses ``compute_portfolio.total_value``, which already prices
    positions at the latest close.
    """
    assert portfolio.id is not None
    # NAV in the book's base currency (Phase 4.8), the unit of opening_nav,
    # so returns compare like with like.
    snap = compute_portfolio(session, portfolio, display_currency=portfolio.base_currency or "USD")
    if not snap.complete:
        # A NAV with a holding at 0 would enter the equity curve and the
        # returns as a real loss. Keep the last good snapshot.
        raise IncompleteValuation("; ".join(w.message for w in snap.warnings))
    nav = Decimal(snap.total_value).quantize(Decimal("0.000001"))

    existing = session.exec(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.date == snapshot_date,
        )
    ).first()
    if existing is None:
        row = PortfolioSnapshot(
            user_id=portfolio.user_id, portfolio_id=portfolio.id, date=snapshot_date, nav=nav
        )
        session.add(row)
    else:
        existing.nav = nav
        row = existing
    session.commit()
    session.refresh(row)
    return row


def upsert_user_snapshot(
    session: Session, *, user_id: int, snapshot_date: date_type
) -> PortfolioSnapshot:
    """The snapshot of the user's default book. ``ValueError`` without one."""
    from stockviz.services.trading.books import default_book

    portfolio = default_book(session, user_id)
    if portfolio is None:
        raise ValueError(f"User {user_id} has no portfolio yet")
    return upsert_book_snapshot(session, portfolio=portfolio, snapshot_date=snapshot_date)


def snapshot_user_navs(session: Session, *, snapshot_date: date_type) -> int:
    """Run ``upsert_book_snapshot`` for every book (A5.1: one row per book).

    Returns the number of snapshots written. Users without a book (a newly
    signed-up account that hasn't visited /portfolio yet) have nothing to
    snapshot. Archived books are snapshotted too: they stay readable, and
    their holdings still move.
    """

    book_ids = list(session.exec(select(Portfolio.id).order_by(Portfolio.id)).all())  # type: ignore[arg-type]
    written = 0
    for book_id in book_ids:
        portfolio = session.get(Portfolio, book_id)
        if portfolio is None:
            continue
        try:
            upsert_book_snapshot(session, portfolio=portfolio, snapshot_date=snapshot_date)
            written += 1
        except IncompleteValuation as exc:
            session.rollback()
            logger.warning(
                "snapshot_user_navs: skipped book %s (user %s), valuation incomplete: %s",
                book_id,
                portfolio.user_id,
                exc,
            )
        except Exception:
            session.rollback()
            logger.exception("snapshot_user_navs: failed for book %s", book_id)
    return written
