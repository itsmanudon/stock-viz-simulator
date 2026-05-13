"""Pending (advanced) order model.

Limit, stop-loss, and take-profit orders sit in ``pending_orders`` until a
daily EOD price triggers settlement. The settlement job fills them at the
close price that triggered the order.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.portfolio import TradeSide


class OrderType(enum.StrEnum):
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


class PendingOrder(SQLModel, table=True):
    __tablename__ = "pending_orders"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)

    side: TradeSide = Field(max_length=8)
    order_type: OrderType = Field(max_length=16)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    limit_price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))

    status: OrderStatus = Field(default=OrderStatus.PENDING, max_length=16, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    filled_at: datetime | None = Field(default=None, nullable=True)
    fill_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
