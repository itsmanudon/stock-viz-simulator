"""Daily portfolio NAV snapshots.

Computes total_value (cash + market value of all positions priced at the most
recent EOD close) for each user and upserts it into ``portfolio_snapshots``.
Idempotent on ``(user_id, date)`` so the scheduler / CLI can re-run safely.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio, PortfolioSnapshot, User
from stockviz.services.trading.portfolio import compute_portfolio

logger = logging.getLogger(__name__)


def upsert_user_snapshot(
    session: Session, *, user_id: int, snapshot_date: date_type
) -> PortfolioSnapshot:
    """Compute today's NAV for ``user_id`` and write/refresh the row.

    Users with no portfolio row yet are skipped at the caller — this helper
    expects an existing portfolio. NAV uses ``compute_portfolio.total_value``,
    which already prices positions at the latest close.
    """

    portfolio = session.exec(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
    ).first()
    if portfolio is None:
        raise ValueError(f"User {user_id} has no portfolio yet")

    snap = compute_portfolio(session, portfolio)
    nav = Decimal(snap.total_value).quantize(Decimal("0.000001"))

    existing = session.exec(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date == snapshot_date,
        )
    ).first()
    if existing is None:
        row = PortfolioSnapshot(user_id=user_id, date=snapshot_date, nav=nav)
        session.add(row)
    else:
        existing.nav = nav
        row = existing
    session.commit()
    session.refresh(row)
    return row


def snapshot_user_navs(session: Session, *, snapshot_date: date_type) -> int:
    """Run ``upsert_user_snapshot`` for every user that owns a portfolio.

    Returns the number of snapshots written. Users without a portfolio (i.e.
    a newly signed-up account that hasn't visited /portfolio yet) are skipped.
    """

    user_ids = list(
        session.exec(
            select(User.id).join(Portfolio, Portfolio.user_id == User.id).distinct()  # type: ignore[arg-type]
        ).all()
    )
    written = 0
    for user_id in user_ids:
        if user_id is None:
            continue
        try:
            upsert_user_snapshot(session, user_id=user_id, snapshot_date=snapshot_date)
            written += 1
        except Exception:
            logger.exception("snapshot_user_navs: failed for user %s", user_id)
    return written
