"""Dividend models.

``Dividend`` is the master calendar: one row per (ticker, ex_date), seeded from
yfinance. ``PortfolioDividend`` records each credit event so we never
double-pay and can show income history.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import instrument_id_column


class Dividend(SQLModel, table=True):
    __tablename__ = "dividends"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("instrument_id", "ex_date", name="uq_dividends_instrument_ex_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))
    ex_date: date_type = Field(nullable=False, index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))


class PortfolioDividend(SQLModel, table=True):
    __tablename__ = "portfolio_dividends"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "instrument_id",
            "ex_date",
            name="uq_portfolio_dividends_portfolio_instrument_date",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))
    ex_date: date_type = Field(nullable=False, index=True)
    # In ``currency``: a dividend in a non-base currency is paid into that
    # currency's cash (Phase 4.5c), like a sale. ``base_value`` is the same
    # credit in the portfolio's base currency at the ex-date rate, for totals.
    amount_credited: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    currency: str = Field(
        default="USD", sa_column=Column(String(3), nullable=False, server_default="USD")
    )
    base_value: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    credited_at: datetime = Field(default_factory=utcnow, nullable=False)
