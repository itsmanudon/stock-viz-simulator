"""Point-in-time company fundamentals (Phase 6.3).

One row per reported figure, never edited: a restatement, or a provider
changing a number, is a new row with a later ``available_at``. "As of date
D" is the latest row for each (concept, period) with ``available_at <= D``
(``services/fundamentals/store.py``). That is the point-in-time rule
backtests need, like ``available_at`` for news.

- ``available_at``: the first day the figure could be known. EDGAR: the
  filing date. yfinance: the day we fetched it, because yfinance gives no
  filing dates; such rows carry ``point_in_time = False`` and pages say so.
- ``concept``: a normalised line item (``revenue``, ``net_income``, ...),
  mapped from the source's own name, kept in ``source_concept``.
- ``period_type``: ``annual``, ``quarter`` (a three-month duration) or
  ``instant`` (a balance-sheet date). Year-to-date durations are not stored.
- ``unit``: a currency (``USD``), ``shares`` or ``<currency>/share``.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Index, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE


class FundamentalFact(SQLModel, table=True):
    __tablename__ = "fundamental_facts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "source",
            "concept",
            "period_type",
            "period_end",
            "available_at",
            name="uq_fundamental_facts_version",
        ),
        Index(
            "ix_fundamental_facts_lookup",
            "instrument_id",
            "concept",
            "period_type",
            "period_end",
            "available_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    concept: str = Field(max_length=48)
    period_type: str = Field(max_length=8)  # annual | quarter | instant
    period_start: date_type | None = None
    period_end: date_type
    fiscal_year: int | None = None
    fiscal_period: str | None = Field(default=None, max_length=4)  # FY, Q1..Q4
    value: Decimal = Field(sa_column=Column(Numeric(28, 6), nullable=False))
    unit: str = Field(max_length=16)
    currency: str | None = Field(default=None, max_length=3)
    available_at: date_type = Field(index=True)
    point_in_time: bool
    source: str = Field(max_length=16)  # edgar | yfinance
    source_concept: str = Field(max_length=160)
    form: str | None = Field(default=None, max_length=16)
    accession: str | None = Field(default=None, max_length=32)
    recorded_at: datetime = Field(default_factory=utcnow, nullable=False)
