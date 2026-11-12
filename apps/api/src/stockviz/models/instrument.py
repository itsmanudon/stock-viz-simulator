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
the instrument when a symbol is added. Batch 4.4 switched reads to
``instrument_id``; 4.6a made it NOT NULL wherever the ticker is. The ticker
keys (``price_bars``' primary key, the ``symbols.ticker`` foreign keys) stay
until writes set ``instrument_id`` themselves: the ORM needs a primary key
it knows at insert time, and a trigger-filled one it does not.
``stockviz.cli instrument-check`` reports any row the triggers missed, and
``instrument-verify`` compares totals read through either key.
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


def instrument_id_column(*, required: bool = False) -> Column:
    """The ``instrument_id`` beside each ``ticker`` column.

    ``required`` (Phase 4.6a) makes it NOT NULL wherever the ticker is NOT
    NULL; only ``news_articles`` (ticker optional) stays nullable. The value
    is still written by the identity trigger, not by the application: the
    Python attribute stays ``None`` until a row is read back. On SQLite the
    trigger runs after the insert, so ``db_identity`` leaves the column
    nullable there (tests only).
    """
    column = Column(ID_TYPE, ForeignKey("instruments.id"), nullable=not required, index=True)
    if required:
        column.info["instrument_id_required"] = True
    return column
