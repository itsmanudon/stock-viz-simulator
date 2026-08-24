"""Price-alert evaluation.

The scheduler's hourly job calls ``evaluate_pending_alerts`` after refreshing
quotes. We compare each pending alert (``triggered_at IS NULL``) against the
latest 1d close for its ticker and flip ``triggered_at`` when the condition
is met. Already-triggered alerts are left alone — dismissing is a UI action.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Alert, AlertDirection, PriceBar

logger = logging.getLogger(__name__)


def _latest_close(session: Session, ticker: str) -> Decimal | None:
    bar = session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return bar.close if bar else None


def evaluate_pending_alerts(
    session: Session,
    *,
    ticker: str | None = None,
    commit: bool = True,
) -> int:
    """Flip ``triggered_at`` on pending alerts whose condition is met.

    ``ticker`` limits the scan to one symbol (event-driven path). ``None``
    keeps the full-universe reconciliation behaviour.
    """

    stmt = select(Alert).where(Alert.triggered_at.is_(None))  # type: ignore[attr-defined]
    if ticker is not None:
        stmt = stmt.where(Alert.ticker == ticker)
    pending = list(session.exec(stmt).all())
    if not pending:
        return 0

    # Cache the latest close per ticker so we don't re-query on every alert.
    cache: dict[str, Decimal | None] = {}
    triggered = 0
    now = utcnow()
    for alert in pending:
        if alert.ticker not in cache:
            cache[alert.ticker] = _latest_close(session, alert.ticker)
        close = cache[alert.ticker]
        if close is None:
            continue
        hit = (
            close >= alert.target_price
            if alert.direction == AlertDirection.ABOVE
            else close <= alert.target_price
        )
        if hit:
            alert.triggered_at = now
            session.add(alert)
            triggered += 1
    if triggered and commit:
        session.commit()
    return triggered
