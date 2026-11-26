"""Intraday bars (A6.1, M2.2 foundation): workspace ``docs/a6-design-note.md``.

A separate table from ``price_bars``: daily timestamps are session labels,
these are instants, and the row is narrow (no ticker string, one index).

- ``intraday_bars``: one row per (instrument, feed, interval, bar open).
  ``ts`` is the bar's **open** instant, naive UTC (like the ledger).
  ``feed`` is where the bar came from: ``iex`` / ``sip`` (US feeds, A6.3
  onwards), ``kite``, or ``file`` (the owner's local files, which never go to
  production: ``services/intraday/guard.py``). ``interval`` is ``1m``, or
  ``60m`` for the hourly files where minutes may not exist; 5/15/30/60 over
  minutes are resampled on read (A6.2). ``source`` names the provider or file
  family (``bulk_1m``, ``bulk_1h``, later ``alpaca_iex_live`` ...), and
  ``file_id`` the exact file. ``available_at`` is when the bar was complete
  (its close instant, clipped at the session close).
- On PostgreSQL the table is range-partitioned by ``ts``, one partition a
  month (``intraday_bars_yYYYYmMM``), created on demand by the writer
  (``services/intraday/partitions.py``). SQLite (tests) has a plain table.
- ``intraday_files``: the provenance of every file loaded: name (never the
  path), SHA-256, size, kind and the counts of its last load.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE

INTRADAY_FEEDS = ("iex", "sip", "kite", "file")
INTRADAY_INTERVALS = ("1m", "60m")
PARTITION_PREFIX = "intraday_bars_y"


class IntradayFile(SQLModel, table=True):
    __tablename__ = "intraday_files"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("kind IN ('bulk_1m', 'bulk_1h')", name="ck_intraday_files_kind"),
    )

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True))
    kind: str = Field(max_length=16)
    file_name: str = Field(max_length=255)
    sha256: str = Field(max_length=64, unique=True)
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    rows_total: int = 0
    rows_accepted: int = 0
    rows_inserted: int = 0
    rows_off_session: int = 0
    rows_invalid: int = 0
    rows_duplicate: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    loaded_at: datetime = Field(default_factory=utcnow, nullable=False)


class IntradayBar(SQLModel, table=True):
    __tablename__ = "intraday_bars"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("feed IN ('iex', 'sip', 'kite', 'file')", name="ck_intraday_bars_feed"),
        CheckConstraint("interval IN ('1m', '60m')", name="ck_intraday_bars_interval"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    # The key is the only index: (instrument, feed, interval, ts). The note's
    # (instrument, feed, ts) gains ``interval`` so a 60-minute bar and the
    # 1-minute bar opening at the same instant can both be stored.
    instrument_id: int = Field(
        sa_column=Column(
            ID_TYPE, ForeignKey("instruments.id"), primary_key=True, autoincrement=False
        )
    )
    feed: str = Field(primary_key=True, max_length=8)
    interval: str = Field(primary_key=True, max_length=4)
    ts: datetime = Field(primary_key=True)

    open: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    high: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    low: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))

    source: str = Field(max_length=24)
    file_id: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("intraday_files.id"), nullable=True)
    )
    ingested_at: datetime = Field(default_factory=utcnow, nullable=False)
    available_at: datetime = Field(nullable=False)
