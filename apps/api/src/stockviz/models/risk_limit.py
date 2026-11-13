"""Pre-trade limits a user sets on their own account (Phase 8.5).

Off until set: every column is nullable, and a portfolio without a row has
no limits. Values are percentages of NAV. The check runs under the portfolio
lock on market orders, pending-order settlement and option opens; sells are
never checked, so reducing a breach is always allowed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Column, Numeric
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

LIMIT_COLUMNS: tuple[str, ...] = (
    "max_position_pct",
    "max_order_pct",
    "max_sector_pct",
    "max_currency_pct",
    "max_var_pct",
)


def _pct() -> Column:
    return Column(Numeric(6, 2), nullable=True)


class RiskLimit(SQLModel, table=True):
    __tablename__ = "risk_limits"  # pyright: ignore[reportAssignmentType]
    __table_args__ = tuple(
        CheckConstraint(
            f"{name} IS NULL OR ({name} > 0 AND {name} <= 100)", name=f"ck_risk_limits_{name}"
        )
        for name in LIMIT_COLUMNS
    )

    portfolio_id: int = Field(foreign_key="portfolios.id", primary_key=True)
    max_position_pct: Decimal | None = Field(default=None, sa_column=_pct())
    max_order_pct: Decimal | None = Field(default=None, sa_column=_pct())
    max_sector_pct: Decimal | None = Field(default=None, sa_column=_pct())
    max_currency_pct: Decimal | None = Field(default=None, sa_column=_pct())
    max_var_pct: Decimal | None = Field(default=None, sa_column=_pct())
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
