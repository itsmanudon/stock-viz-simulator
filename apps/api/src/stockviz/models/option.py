"""Options paper-trading model.

A single long-options book per user: you buy a call or put to open, sell it
to close before expiry, or let it run to expiry where the settlement job
exercises it (ITM) or expires it worthless (OTM). Writing/shorting options is
out of scope for v1 — every row here is a long position.

A contract opens covering ``CONTRACT_MULTIPLIER`` shares (the US
equity-option standard of 100). ``shares_per_contract`` is stored per row
because a split changes it: a 4-for-1 split turns a 100-share contract at a
$200 strike into a 400-share contract at $50 (Phase 4.2, #65).
"""

from __future__ import annotations

import enum
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import instrument_id_column

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
    # The Trading Journal scans one user's settled contracts over a month.
    # Composite so that range scan doesn't fall back to the user_id index and
    # then filter every historical row by hand.
    __table_args__ = (
        Index("ix_options_positions_user_settled", "user_id", "settled_at"),
        CheckConstraint(
            "quantity > 0 AND strike > 0 AND premium_paid >= 0",
            name="ck_options_positions_amounts_valid",
        ),
        # A repeated open with the same client key returns the first contract
        # (audit LG-10). NULLs never clash.
        UniqueConstraint(
            "portfolio_id",
            "client_order_id",
            name="uq_options_positions_portfolio_client_order_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))

    option_type: OptionType = Field(max_length=4)
    strike: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    expiry: date_type = Field(nullable=False, index=True)
    quantity: int = Field(nullable=False)  # number of contracts
    shares_per_contract: Decimal = Field(
        default=Decimal(CONTRACT_MULTIPLIER),
        sa_column=Column(Numeric(18, 6), nullable=False, server_default="100"),
    )
    premium_paid: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    client_order_id: str | None = Field(default=None, max_length=64, nullable=True)

    status: OptionStatus = Field(default=OptionStatus.OPEN, max_length=12, index=True)
    opened_at: datetime = Field(default_factory=utcnow, nullable=False)
    settled_at: datetime | None = Field(default=None, nullable=True)

    # Terminal-event accounting, written once when the position leaves OPEN.
    # ``proceeds`` is the cash actually credited by that event; ``realized_pnl``
    # is the USD gain/loss over the contract's whole life. Both stay NULL on
    # OPEN rows, and on CLOSED/EXERCISED rows written before these columns
    # existed — their proceeds were never persisted and re-pricing them today
    # would not be reproducible, so the Trading Journal excludes them rather
    # than inventing a number. See docs/TRADING_JOURNAL.md.
    proceeds: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6), nullable=True))
    realized_pnl: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 6), nullable=True)
    )
