"""Scheduled and reported earnings events.

The calendar deliberately stores only provider facts. Beat/miss labels are
derived at read time from reported and estimated EPS, and are left unknown
when either value is unavailable.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class EarningsEvent(SQLModel, table=True):
    __tablename__ = "earnings_events"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "ticker", "event_date", "fiscal_period", name="uq_earnings_events_identity"
        ),
        Index("ix_earnings_events_date_ticker", "event_date", "ticker"),
    )

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    event_date: date_type = Field(index=True, nullable=False)
    # Provider values are intentionally unopinionated strings. yfinance uses
    # BMO, AMC, and sometimes an explicit local-time label.
    report_time: str | None = Field(default=None, max_length=32)
    fiscal_period: str = Field(default="", max_length=32, nullable=False)
    eps_estimate: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    eps_actual: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    surprise_pct: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    source: str = Field(default="yfinance", max_length=32, nullable=False)
    fetched_at: datetime = Field(default_factory=utcnow, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
