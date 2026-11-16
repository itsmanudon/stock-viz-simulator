"""Multi-leg option strategies (Phase 9.3).

A strategy groups legs (``options_positions`` rows with ``strategy_id``) that
were opened together from one template and close together by default. The
legs keep their own accounting; the strategy records what the template was,
the net premium (positive when credited), what it held back and the most it
can lose and gain, as figured at open. ``collateral`` is reserved from cash
while any of its short legs covered by another leg is open.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class StrategyKind(enum.StrEnum):
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    PROTECTIVE_PUT = "protective_put"
    BULL_CALL = "bull_call"
    BEAR_PUT = "bear_put"
    BULL_PUT = "bull_put"
    BEAR_CALL = "bear_call"
    IRON_CONDOR = "iron_condor"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    CALENDAR = "calendar"


class StrategyStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"  # every leg closed by the user
    SETTLED = "settled"  # no leg open, and at least one was settled at expiry


class OptionStrategy(SQLModel, table=True):
    __tablename__ = "option_strategies"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "client_order_id",
            name="uq_option_strategies_portfolio_client_order_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    kind: str = Field(sa_column=Column(String(24), nullable=False))
    status: str = Field(
        default=StrategyStatus.OPEN, sa_column=Column(String(12), nullable=False, index=True)
    )
    # USD. Positive when the open credited cash, negative when it was paid.
    net_premium: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    collateral: Decimal = Field(
        default=Decimal(0), sa_column=Column(Numeric(20, 6), nullable=False, server_default="0")
    )
    max_loss: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6)))
    max_gain: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6)))
    client_order_id: str | None = Field(default=None, max_length=64, nullable=True)
    opened_at: datetime = Field(default_factory=utcnow, nullable=False)
    settled_at: datetime | None = Field(default=None, nullable=True)
