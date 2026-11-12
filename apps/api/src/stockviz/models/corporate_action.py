"""Corporate actions and their application to the ledger (Phase 4.2, #65).

yfinance's daily history is split-adjusted, and the nightly ingest upserts the
whole history, so after a split every stored bar is rescaled while positions,
pending orders, alert targets and option strikes stayed on the old scale: a
4-for-1 split read as a 75% loss. ``corporate_actions`` records each split
(from ``yfinance.Ticker.splits``) and ``corporate_action_applications`` records,
once per user, that the ledger was rebased for it. See
``services/corporate_actions/``.

Only splits for now (Indian bonus issues arrive as splits too). Dividends keep
their own table; mergers, spin-offs and ticker changes are out of scope.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Column, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

SPLIT = "split"


class CorporateAction(SQLModel, table=True):
    """``ratio_to`` new shares for every ``ratio_from`` old ones, from ``ex_date``.

    A 4-for-1 split is 1 -> 4; a 1-for-10 reverse split is 10 -> 1.
    """

    __tablename__ = "corporate_actions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("ticker", "kind", "ex_date", name="uq_corporate_actions_ticker_kind_ex"),
        CheckConstraint(
            "ratio_from > 0 AND ratio_to > 0", name="ck_corporate_actions_ratio_positive"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    kind: str = Field(max_length=16)
    ex_date: date_type = Field(nullable=False, index=True)
    ratio_from: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    ratio_to: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    source: str = Field(max_length=32)
    recorded_at: datetime = Field(default_factory=utcnow, nullable=False)

    @property
    def ratio(self) -> Decimal:
        return self.ratio_to / self.ratio_from


class CorporateActionApplication(SQLModel, table=True):
    """One user's ledger was rebased for one action. Unique, so a rerun is a no-op."""

    __tablename__ = "corporate_action_applications"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("action_id", "user_id", name="uq_corporate_action_applications"),
    )

    id: int | None = Field(default=None, primary_key=True)
    action_id: int = Field(foreign_key="corporate_actions.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    applied_at: datetime = Field(default_factory=utcnow, nullable=False)
    # What changed, for the audit trail: "position 10 -> 40; 1 order; 0 alerts".
    summary: str = Field(max_length=500)
