"""Paper-trading models: portfolios, positions, trades, daily snapshots.

All monetary values are ``Decimal`` so position math stays exact. Quantities
are also ``Decimal`` to leave room for fractional shares.
"""

from __future__ import annotations

import enum
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class TradeSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class Portfolio(SQLModel, table=True):
    __tablename__ = "portfolios"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    # One default paper book per user — concurrent first-use INSERTs collide
    # on this unique index and retry as a read of the winner's row.
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    name: str = Field(default="Default", max_length=128)
    cash_balance: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Position(SQLModel, table=True):
    """Aggregated holding for one (portfolio, ticker).

    Maintained as a materialized roll-up of trades for fast portfolio reads.
    Written by ``services/trading/execute.py::apply_fill`` — the single fill
    path shared by market orders and pending-order settlement.
    """

    __tablename__ = "positions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)

    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    avg_cost: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))


class Trade(SQLModel, table=True):
    __tablename__ = "trades"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)

    side: TradeSide = Field(max_length=8)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    ts: datetime = Field(default_factory=utcnow, nullable=False, index=True)

    # USD per one unit of the symbol's native currency, captured at fill time.
    # Persisting it means the trade log can show what the fill actually cost
    # instead of re-converting historical trades at today's rate. 1 for USD
    # symbols; NULL only on rows written before this column existed.
    fx_rate: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 8), nullable=True))
    # Realized P&L in USD against the position's weighted-average cost basis.
    # Set on sells; NULL on buys (a buy realizes nothing).
    realized_pnl: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 6), nullable=True)
    )


class PortfolioSnapshot(SQLModel, table=True):
    """One row per user per day with the portfolio's net asset value.

    Written by an APScheduler job after the daily price refresh. The
    ``(user_id, date)`` uniqueness lets the writer use upsert / idempotent
    re-runs without piling up duplicates.
    """

    __tablename__ = "portfolio_snapshots"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_portfolio_snapshots_user_date"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    date: date_type = Field(nullable=False, index=True)
    nav: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
