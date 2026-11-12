"""Record share splits from yfinance into ``corporate_actions``.

``yfinance.Ticker(t).splits`` is a Series of ex-date -> ratio, where 4.0 is a
4-for-1 split and 0.1 a 1-for-10 reverse split. The ratio is turned into a
whole-number pair (1 -> 4, 10 -> 1) so the rebase stays exact. Idempotent on
(ticker, kind, ex_date); a corrected ratio updates the row only while no
user has had it applied.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from fractions import Fraction

from sqlmodel import Session, col, select

from stockviz.models import CorporateAction, CorporateActionApplication

logger = logging.getLogger(__name__)

SOURCE_YFINANCE = "yfinance"

SplitFetchFn = Callable[[str], list[tuple[date, float]]]
"""(ticker) -> [(ex_date, ratio)], ratio new shares per old share."""


def _default_split_fetch(ticker: str) -> list[tuple[date, float]]:
    import yfinance as yf

    series = yf.Ticker(ticker).splits
    if series is None or series.empty:
        return []
    out: list[tuple[date, float]] = []
    for ts, ratio in series.items():
        try:
            out.append((date.fromisoformat(str(ts)[:10]), float(ratio)))
        except (TypeError, ValueError):
            continue
    return out


def ratio_pair(ratio: float) -> tuple[Decimal, Decimal] | None:
    """(ratio_from, ratio_to) for a yfinance ratio, or None if it is unusable."""

    if not ratio or ratio <= 0 or ratio != ratio:  # zero, negative or NaN
        return None
    fraction = Fraction(str(ratio)).limit_denominator(1000)
    if fraction <= 0 or fraction == 1:
        return None
    return Decimal(fraction.denominator), Decimal(fraction.numerator)


def record_splits(
    session: Session,
    ticker: str,
    *,
    fetch_fn: SplitFetchFn | None = None,
) -> int:
    """Upsert ``ticker``'s splits. Returns rows added or changed. Does not commit.

    ``fetch_fn`` defaults to the yfinance call, looked up at call time so tests
    can replace the module attribute.
    """

    changed = 0
    for ex_date, ratio in (fetch_fn or _default_split_fetch)(ticker):
        pair = ratio_pair(ratio)
        if pair is None:
            logger.warning("splits: %s %s ratio %r ignored", ticker, ex_date, ratio)
            continue
        ratio_from, ratio_to = pair
        existing = session.exec(
            select(CorporateAction).where(
                col(CorporateAction.ticker) == ticker,
                col(CorporateAction.kind) == "split",
                col(CorporateAction.ex_date) == ex_date,
            )
        ).first()
        if existing is None:
            session.add(
                CorporateAction(
                    ticker=ticker,
                    kind="split",
                    ex_date=ex_date,
                    ratio_from=ratio_from,
                    ratio_to=ratio_to,
                    source=SOURCE_YFINANCE,
                )
            )
            changed += 1
            continue
        if (existing.ratio_from, existing.ratio_to) == (ratio_from, ratio_to):
            continue
        applied = session.exec(
            select(CorporateActionApplication).where(
                col(CorporateActionApplication.action_id) == existing.id
            )
        ).first()
        if applied is not None:
            logger.warning(
                "splits: %s %s ratio changed to %s:%s after it was applied; kept %s:%s",
                ticker,
                ex_date,
                ratio_from,
                ratio_to,
                existing.ratio_from,
                existing.ratio_to,
            )
            continue
        existing.ratio_from, existing.ratio_to = ratio_from, ratio_to
        session.add(existing)
        changed += 1
    return changed


def ledger_tickers(session: Session) -> list[str]:
    """Tickers a split could matter for: held, ordered, alerted or optioned.

    Fetching only these keeps the nightly call count to the ledger's size
    rather than the whole universe.
    """

    from stockviz.models import (
        Alert,
        OptionsPosition,
        OptionStatus,
        OrderStatus,
        PendingOrder,
        Position,
    )

    tickers: set[str] = set()
    tickers.update(session.exec(select(Position.ticker).where(col(Position.quantity) > 0)).all())
    tickers.update(
        session.exec(
            select(PendingOrder.ticker).where(col(PendingOrder.status) == OrderStatus.PENDING)
        ).all()
    )
    tickers.update(
        session.exec(
            select(Alert.ticker).where(
                col(Alert.triggered_at).is_(None), col(Alert.dismissed_at).is_(None)
            )
        ).all()
    )
    tickers.update(
        session.exec(
            select(OptionsPosition.ticker).where(col(OptionsPosition.status) == OptionStatus.OPEN)
        ).all()
    )
    return sorted(tickers)
