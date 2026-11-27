"""Macro series and their observations (A9.7, M1.10).

``MacroSeries`` is one provider series (today only FRED), with the metadata
the provider reports and the time StockViz last fetched it.
``MacroObservation`` is one dated value. A null ``value`` is a date the
provider lists without a number (FRED writes ``"."``): it is kept so a gap
reads as a gap, not as a missing fetch.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlmodel import Column, Field, SQLModel


class MacroSeries(SQLModel, table=True):
    __tablename__ = "macro_series"  # pyright: ignore[reportAssignmentType]

    series_id: str = Field(sa_column=Column(String(40), primary_key=True))
    provider: str = Field(default="fred", max_length=16)
    title: str = Field(max_length=300)
    units: str = Field(default="", max_length=120)
    frequency: str = Field(default="", max_length=40)
    observation_start: date_type | None = None
    observation_end: date_type | None = None
    provider_updated: str | None = Field(default=None, max_length=40)
    fetched_at: datetime | None = None


class MacroObservation(SQLModel, table=True):
    __tablename__ = "macro_observations"  # pyright: ignore[reportAssignmentType]

    series_id: str = Field(
        sa_column=Column(String(40), primary_key=True),
    )
    obs_date: date_type = Field(primary_key=True)
    value: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6), nullable=True))
