"""Options paper-trading model.

A single long-options book per user: you buy a call or put to open, sell it
to close before expiry, or let it run to expiry where the settlement job
exercises it (ITM) or expires it worthless (OTM). Writing/shorting options is
out of scope for v1 — every row here is a long position.

One contract covers ``CONTRACT_MULTIPLIER`` shares (the US equity-option
standard of 100).
"""

from __future__ import annotations

import enum
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow

CONTRACT_MULTIPLIER = 100
"""Shares of the underlying covered by one option contract."""


class OptionType(enum.StrEnum):
    CALL = "call"
    PUT = "put"


class OptionStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"  # sold to close before expiry
    EXERCISED = "exercised"  # in-the-money at expiry, settled
    EXPIRED = "expired"  # out-of-the-money at expiry, worthless


class OptionsPosition(SQLModel, table=True):
    __tablename__ = "options_positions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)

    option_type: OptionType = Field(max_length=4)
    strike: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    expiry: date_type = Field(nullable=False, index=True)
    quantity: int = Field(nullable=False)  # number of contracts
    premium_paid: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))

    status: OptionStatus = Field(default=OptionStatus.OPEN, max_length=12, index=True)
    opened_at: datetime = Field(default_factory=utcnow, nullable=False)
    settled_at: datetime | None = Field(default=None, nullable=True)
