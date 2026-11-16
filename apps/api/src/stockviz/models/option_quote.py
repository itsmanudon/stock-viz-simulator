"""Nightly option-chain snapshots (Phase 9.6).

One row per listed contract per snapshot day: bid, ask, last, volume, open
interest as the provider reported them, the price used (the bid-ask mid
when both are quoted, else the last trade) and the implied volatility
solved from it against that day's stored close. Keyed by instrument, so a
ticker change keeps its history. History starts the day collection starts:
there is no backfill of past chains.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Numeric, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE


class OptionChainQuote(SQLModel, table=True):
    __tablename__ = "option_quotes"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "snapshot_date",
            "expiry",
            "strike",
            "option_type",
            name="uq_option_quotes_contract_day",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    snapshot_date: date_type = Field(nullable=False, index=True)
    expiry: date_type = Field(nullable=False)
    strike: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    option_type: str = Field(sa_column=Column(String(4), nullable=False))
    bid: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    ask: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    last: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    price: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    implied_volatility: float | None = Field(default=None)
    volume: int | None = Field(default=None)
    open_interest: int | None = Field(default=None)
    source: str = Field(default="yfinance", sa_column=Column(String(16), nullable=False))
    fetched_at: datetime = Field(default_factory=utcnow, nullable=False)
