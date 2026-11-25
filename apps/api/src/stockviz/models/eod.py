"""NSE end-of-day rows as the exchange published them (A1.1).

``eod_raw`` holds the cash bhavcopy per instrument, session and series:
open, high, low, close, last, previous close, volume, turnover (rupees) and
trades. These are the exchange's own numbers and are never adjusted in place;
A1.3 computes split-adjusted ``price_bars`` from them. ``eod_extras`` holds
delivery quantity and delivery % from ``sec_bhavdata_full``.

Both are keyed by ``instrument_id`` only. They have no ``ticker`` column, so
the ticker identity machinery (triggers, ``TICKER_TABLES``) does not apply:
the loader resolves the instrument itself (``services/nse/load.py``).
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Column, Date, ForeignKey, Numeric, String
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE


def _instrument_key() -> Column:
    return Column(ID_TYPE, ForeignKey("instruments.id"), primary_key=True, autoincrement=False)


def _data_file_key() -> Column:
    return Column(ID_TYPE, ForeignKey("data_files.id"), nullable=False, index=True)


class EodRaw(SQLModel, table=True):
    __tablename__ = "eod_raw"  # pyright: ignore[reportAssignmentType]

    instrument_id: int = Field(sa_column=_instrument_key())
    session_date: date_type = Field(sa_column=Column(Date, primary_key=True, index=True))
    series: str = Field(sa_column=Column(String(4), primary_key=True))
    open: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    high: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    low: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    last: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    prev_close: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))
    # Rupees. sec_bhavdata_full's lakhs are never stored here.
    turnover: Decimal | None = Field(default=None, sa_column=Column(Numeric(24, 4)))
    trades: int | None = Field(default=None)
    isin: str | None = Field(default=None, max_length=12)
    source: str = Field(max_length=32)
    data_file_id: int = Field(sa_column=_data_file_key())
    loaded_at: datetime = Field(default_factory=utcnow, nullable=False)


class EodExtras(SQLModel, table=True):
    __tablename__ = "eod_extras"  # pyright: ignore[reportAssignmentType]

    instrument_id: int = Field(sa_column=_instrument_key())
    session_date: date_type = Field(sa_column=Column(Date, primary_key=True, index=True))
    series: str = Field(sa_column=Column(String(4), primary_key=True))
    deliverable_qty: int | None = Field(default=None, sa_column=Column(BigInteger))
    delivery_pct: Decimal | None = Field(default=None, sa_column=Column(Numeric(7, 2)))
    data_file_id: int = Field(sa_column=_data_file_key())
    loaded_at: datetime = Field(default_factory=utcnow, nullable=False)
