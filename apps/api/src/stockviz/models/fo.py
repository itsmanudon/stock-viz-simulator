"""NSE index options from the owner's minute files, as daily summaries (A7.14, M6.1).

The owner's files (27 Nov 2026: load into a local database only, like the
minute files) hold continuous minute series by strike offset from the money
(ATM, ATM+1, ATM-2, ...) with premium, OI, implied volatility and spot, but
no strike or expiry. StockViz keeps one row per (underlying, series, day,
option type, offset): the day's last minute (premium, IV, OI, spot) and the
day's summed volume. The minutes stay in the owner's files.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Numeric, String
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class FoDaily(SQLModel, table=True):
    __tablename__ = "fo_daily"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("option_type IN ('CE', 'PE')", name="ck_fo_daily_option_type"),
    )

    underlying: str = Field(sa_column=Column(String(24), primary_key=True))
    series: str = Field(sa_column=Column(String(16), primary_key=True))
    day: date_type = Field(primary_key=True)
    option_type: str = Field(sa_column=Column(String(2), primary_key=True))
    strike_offset: int = Field(primary_key=True)
    close: Decimal = Field(sa_column=Column(Numeric(18, 4), nullable=False))
    iv: float | None = None
    oi: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))
    spot: Decimal = Field(sa_column=Column(Numeric(18, 4), nullable=False))
    last_minute: str = Field(max_length=8)
    minutes: int


class FoFile(SQLModel, table=True):
    __tablename__ = "fo_files"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    sha256: str = Field(max_length=64, unique=True)
    file_name: str = Field(max_length=255)
    series: str = Field(max_length=16)
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    rows_total: int
    rows_rejected: int
    loaded_at: datetime = Field(default_factory=utcnow)
