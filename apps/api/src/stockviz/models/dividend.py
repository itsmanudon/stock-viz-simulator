"""Dividend models.

``Dividend`` is the master calendar: one row per (ticker, ex_date), seeded from
yfinance. ``PortfolioDividend`` records each credit event so we never
double-pay and can show income history.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class Dividend(SQLModel, table=True):
    __tablename__ = "dividends"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("ticker", "ex_date", name="uq_dividends_ticker_ex_date"),)

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    ex_date: date_type = Field(nullable=False, index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))


class PortfolioDividend(SQLModel, table=True):
    __tablename__ = "portfolio_dividends"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "ticker", "ex_date", name="uq_portfolio_dividends_portfolio_ticker_date"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    ex_date: date_type = Field(nullable=False, index=True)
    amount_credited: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    credited_at: datetime = Field(default_factory=utcnow, nullable=False)
