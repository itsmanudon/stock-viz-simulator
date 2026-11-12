"""Instrument identity (Phase 4.3, expand step).

The ticker string (``RELIANCE.NS``) is still the primary key of ``symbols``
and the foreign key everywhere. This step adds the identity the design note
sets out (workspace ``docs/phase-4-design-note.md`` section 2) beside it:

- ``instruments``: one row per listing, with its venue (ISO 10383 MIC), the
  currency it trades in and the unit its prices arrive in (``GBX`` for London
  pence, audit MD-2);
- ``instrument_identifiers``: the names other systems use for it (scheme
  ``yahoo`` = today's ticker, ``aegis`` = ``stockviz:<ticker>``), so a renamed
  or second listing is a new identifier row, not a new key.

Every table with a ``ticker`` column gains a nullable ``instrument_id``.
Postgres triggers fill it on every write (``stockviz_fill_instrument_id``),
including the bulk ``price_bars`` upsert that bypasses the ORM, and create
the instrument when a symbol is added. Nothing reads ``instrument_id`` yet:
batch 4.4 switches reads, and only 4.6 (separately approved) makes it NOT
NULL and drops the ticker keys. ``stockviz.cli instrument-check`` reports
any row the triggers missed.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

# bigint in Postgres; SQLite only autoincrements INTEGER PRIMARY KEY.
ID_TYPE = BigInteger().with_variant(Integer(), "sqlite")

SCHEME_YAHOO = "yahoo"
SCHEME_AEGIS = "aegis"


class Instrument(SQLModel, table=True):
    __tablename__ = "instruments"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("symbol", "mic", name="uq_instruments_symbol_mic"),)

    id: int | None = Field(default=None, sa_column=Column(ID_TYPE, primary_key=True))
    # The venue's own symbol: the Yahoo suffix is dropped (BARC.L -> BARC).
    symbol: str = Field(max_length=16)
    mic: str | None = Field(default=None, max_length=4)
    country: str | None = Field(default=None, max_length=2)
    currency: str = Field(max_length=3)
    quote_unit: str = Field(max_length=3)
    asset_type: str = Field(default="equity", max_length=16)
    status: str = Field(default="active", max_length=16)
    listed_on: date_type | None = None
    delisted_on: date_type | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class InstrumentIdentifier(SQLModel, table=True):
    __tablename__ = "instrument_identifiers"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "scheme", "value", "valid_from", name="uq_instrument_identifiers_scheme_value_from"
        ),
    )

    id: int | None = Field(default=None, sa_column=Column(ID_TYPE, primary_key=True))
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    scheme: str = Field(max_length=16)
    value: str = Field(max_length=64)
    valid_from: date_type = Field(nullable=False)
    valid_to: date_type | None = None


def instrument_id_column() -> Column:
    """The nullable ``instrument_id`` added beside each ``ticker`` column."""
    return Column(ID_TYPE, ForeignKey("instruments.id"), nullable=True, index=True)
