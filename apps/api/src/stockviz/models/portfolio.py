"""Paper-trading models: portfolios, positions, trades.

All monetary values are ``Decimal`` so position math stays exact. Quantities
are also ``Decimal`` to leave room for fractional shares.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class TradeSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class Portfolio(SQLModel, table=True):
    __tablename__ = "portfolios"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(default="Default", max_length=128)
    cash_balance: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Position(SQLModel, table=True):
    """Aggregated holding for one (portfolio, ticker).

    Maintained as a materialized roll-up of trades for fast portfolio reads.
    Phase 6 will write the recompute logic; for now the schema is in place.
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
