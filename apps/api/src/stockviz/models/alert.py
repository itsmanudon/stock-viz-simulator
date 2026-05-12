"""Per-user price alerts.

A user sets a target price (``above`` or ``below``) on a ticker; the scheduler
flips ``triggered_at`` from null to the trigger timestamp when a fresh quote
crosses the threshold. The UI shows a bell-badge of triggered-but-undismissed
alerts and lets the user dismiss them.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class AlertDirection(enum.StrEnum):
    ABOVE = "above"
    BELOW = "below"


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    direction: AlertDirection = Field(max_length=8)
    target_price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    triggered_at: datetime | None = Field(default=None, nullable=True)
    dismissed_at: datetime | None = Field(default=None, nullable=True)
