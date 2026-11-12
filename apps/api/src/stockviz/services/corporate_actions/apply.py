"""Rebase the ledger for a share split (Phase 4.2, #65).

Stored bars are yfinance's split-adjusted series, rewritten in full every
night, so after a split the old closes are divided by the ratio while the
ledger was still in old shares. This module brings the ledger onto the new
scale, once per (split, user).

**Which rows are on the old scale.** A trade, order, alert or option made
before the split took effect was priced against unsplit closes. The cut-off
is the moment the ex-date session's bar is complete on the ticker's venue
(``session_complete_at``): before it, fills used the prior close, which was
unsplit; after the nightly ingest the closes are split. (A fill between that
moment and the ingest is counted as new-scale; the gap is minutes.)

**What changes**, for ratio r (new shares per old share):

- position: the shares bought before the cut-off and still held are
  multiplied by r; the total cost basis is kept, so ``avg_cost`` falls. Shares
  bought after the cut-off are already new-scale and stay;
- pending orders placed before the cut-off: ``quantity * r``,
  ``limit_price / r``;
- untriggered alerts set before the cut-off: ``target_price / r``;
- open options opened before the cut-off: ``strike / r``,
  ``shares_per_contract * r``.

Trade rows are history and stay as filled. Cash does not change.

**Old splits are no-ops.** yfinance returns every split a ticker ever had
(AAPL's 2020 4-for-1 among them). Nothing in the ledger predates those, so a
first run records them and changes nothing.

**Once only.** ``corporate_action_applications`` is unique on (action, user)
and is written in the same transaction as the rebase, so a rerun skips it.
A split becomes due once its ex-date session is complete on the venue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import (
    Alert,
    CorporateAction,
    CorporateActionApplication,
    OptionsPosition,
    OptionStatus,
    OrderStatus,
    PendingOrder,
    Portfolio,
    Position,
    Trade,
    TradeSide,
)
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import (
    latest_completed_session,
    session_complete_at,
    venue_for_ticker,
)

logger = logging.getLogger(__name__)

_QTY = Decimal("0.000001")
_PRICE = Decimal("0.000001")


@dataclass
class RebaseSummary:
    position: tuple[Decimal, Decimal] | None = None  # quantity before, after
    orders: int = 0
    alerts: int = 0
    options: int = 0

    def changed(self) -> bool:
        return bool(self.position or self.orders or self.alerts or self.options)

    def text(self) -> str:
        parts = []
        if self.position:
            before, after = self.position
            parts.append(f"position {before.normalize()} -> {after.normalize()}")
        parts.append(f"{self.orders} order(s), {self.alerts} alert(s), {self.options} option(s)")
        return "; ".join(parts)


@dataclass
class ApplyResult:
    actions_due: int = 0
    users_rebased: int = 0
    summaries: list[str] = field(default_factory=list)


def _naive_utc(value: datetime) -> datetime:
    """Ledger timestamps are naive UTC."""
    return value.astimezone(UTC).replace(tzinfo=None)


def cutoff(action: CorporateAction) -> datetime:
    """Naive-UTC moment from which prices for ``action.ticker`` are split."""
    return _naive_utc(session_complete_at(action.ex_date, venue_for_ticker(action.ticker)))


def due_actions(session: Session, now: datetime) -> list[CorporateAction]:
    """Splits whose ex-date session is complete on their venue at ``now``."""

    actions = session.exec(
        select(CorporateAction)
        .where(col(CorporateAction.kind) == "split")
        .order_by(col(CorporateAction.ex_date), col(CorporateAction.id))
    ).all()
    return [
        a for a in actions if a.ex_date <= latest_completed_session(now, venue_for_ticker(a.ticker))
    ]


def _shares_held_before(
    session: Session, portfolio_id: int, ticker: str, before: datetime
) -> Decimal:
    trades = session.exec(
        select(Trade).where(
            col(Trade.portfolio_id) == portfolio_id,
            col(Trade.instrument_id) == instrument_of(ticker),
            col(Trade.ts) < before,
        )
    ).all()
    held = Decimal(0)
    for trade in trades:
        held += trade.quantity if trade.side == TradeSide.BUY else -trade.quantity
    return held


def _candidate_user_ids(session: Session, action: CorporateAction, before: datetime) -> set[int]:
    """Users with something on the old scale for this ticker."""

    ticker = action.ticker
    users: set[int] = set()
    holders = session.exec(
        select(Portfolio.user_id)
        .join(Position, col(Position.portfolio_id) == col(Portfolio.id))
        .where(col(Position.instrument_id) == instrument_of(ticker))
    ).all()
    users.update(holders)
    orders = session.exec(
        select(Portfolio.user_id)
        .join(PendingOrder, col(PendingOrder.portfolio_id) == col(Portfolio.id))
        .where(
            col(PendingOrder.instrument_id) == instrument_of(ticker),
            col(PendingOrder.status) == OrderStatus.PENDING,
            col(PendingOrder.created_at) < before,
        )
    ).all()
    users.update(orders)
    alerts = session.exec(
        select(Alert.user_id).where(
            col(Alert.instrument_id) == instrument_of(ticker),
            col(Alert.triggered_at).is_(None),
            col(Alert.dismissed_at).is_(None),
            col(Alert.created_at) < before,
        )
    ).all()
    users.update(alerts)
    options = session.exec(
        select(OptionsPosition.user_id).where(
            col(OptionsPosition.instrument_id) == instrument_of(ticker),
            col(OptionsPosition.status) == OptionStatus.OPEN,
            col(OptionsPosition.opened_at) < before,
        )
    ).all()
    users.update(options)
    return users


def _already_applied(session: Session, action_id: int, user_id: int) -> bool:
    return (
        session.exec(
            select(CorporateActionApplication).where(
                col(CorporateActionApplication.action_id) == action_id,
                col(CorporateActionApplication.user_id) == user_id,
            )
        ).first()
        is not None
    )


def rebase_user(session: Session, action: CorporateAction, user_id: int) -> RebaseSummary:
    """Rebase one user's ledger for ``action``. Stages changes; does not commit."""

    assert action.id is not None
    ratio = action.ratio
    before = cutoff(action)
    ticker = action.ticker
    summary = RebaseSummary()

    portfolio = session.exec(
        select(Portfolio).where(col(Portfolio.user_id) == user_id).with_for_update()
    ).first()
    if portfolio is not None and portfolio.id is not None:
        position = session.exec(
            select(Position).where(
                col(Position.portfolio_id) == portfolio.id,
                col(Position.instrument_id) == instrument_of(ticker),
            )
        ).first()
        if position is not None and position.quantity > 0:
            old_scale = min(
                max(_shares_held_before(session, portfolio.id, ticker, before), Decimal(0)),
                position.quantity,
            )
            if old_scale > 0:
                cost = position.quantity * position.avg_cost
                quantity = (position.quantity + old_scale * (ratio - 1)).quantize(_QTY)
                summary.position = (position.quantity, quantity)
                position.quantity = quantity
                position.avg_cost = (cost / quantity).quantize(_PRICE)
                session.add(position)

        orders = session.exec(
            select(PendingOrder).where(
                col(PendingOrder.portfolio_id) == portfolio.id,
                col(PendingOrder.instrument_id) == instrument_of(ticker),
                col(PendingOrder.status) == OrderStatus.PENDING,
                col(PendingOrder.created_at) < before,
            )
        ).all()
        for order in orders:
            order.quantity = (order.quantity * ratio).quantize(_QTY)
            order.limit_price = (order.limit_price / ratio).quantize(_PRICE)
            session.add(order)
        summary.orders = len(orders)

    alerts = session.exec(
        select(Alert).where(
            col(Alert.user_id) == user_id,
            col(Alert.instrument_id) == instrument_of(ticker),
            col(Alert.triggered_at).is_(None),
            col(Alert.dismissed_at).is_(None),
            col(Alert.created_at) < before,
        )
    ).all()
    for alert in alerts:
        alert.target_price = (alert.target_price / ratio).quantize(_PRICE)
        session.add(alert)
    summary.alerts = len(alerts)

    options = session.exec(
        select(OptionsPosition).where(
            col(OptionsPosition.user_id) == user_id,
            col(OptionsPosition.instrument_id) == instrument_of(ticker),
            col(OptionsPosition.status) == OptionStatus.OPEN,
            col(OptionsPosition.opened_at) < before,
        )
    ).all()
    for option in options:
        option.strike = (option.strike / ratio).quantize(_PRICE)
        option.shares_per_contract = (option.shares_per_contract * ratio).quantize(_QTY)
        session.add(option)
    summary.options = len(options)

    session.add(
        CorporateActionApplication(action_id=action.id, user_id=user_id, summary=summary.text())
    )
    return summary


def apply_due_splits(session: Session, *, now: datetime) -> ApplyResult:
    """Rebase every affected user for every due split, one commit per user."""

    result = ApplyResult()
    for action in due_actions(session, now):
        result.actions_due += 1
        assert action.id is not None
        before = cutoff(action)
        for user_id in sorted(_candidate_user_ids(session, action, before)):
            if _already_applied(session, action.id, user_id):
                continue
            summary = rebase_user(session, action, user_id)
            session.commit()
            if summary.changed():
                result.users_rebased += 1
                line = (
                    f"{action.ticker} {action.ex_date} {action.ratio_from.normalize()}:"
                    f"{action.ratio_to.normalize()} user {user_id}: {summary.text()}"
                )
                result.summaries.append(line)
                logger.info("corporate actions: %s", line)
    return result
