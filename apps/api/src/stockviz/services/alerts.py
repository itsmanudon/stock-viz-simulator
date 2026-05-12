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


def evaluate_pending_alerts(session: Session) -> int:
    """Flip ``triggered_at`` on every pending alert whose condition is met.

    Returns the number of alerts triggered in this pass. Pending = not yet
    triggered. Dismissed-but-untriggered shouldn't really exist (you can't
    dismiss before it triggers), but if they do we treat them like any other
    pending row.
    """

    pending = list(session.exec(select(Alert).where(Alert.triggered_at.is_(None))).all())  # type: ignore[attr-defined]
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
    if triggered:
        session.commit()
    return triggered
