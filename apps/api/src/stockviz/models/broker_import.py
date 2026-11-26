"""Broker tradebook imports (A5.3, M10.2 CSV part): batches and normalised fills.

A Zerodha Console tradebook CSV is parsed (``services/imports/``) into one
``broker_fills`` row per trade, grouped by the ``import_batches`` row of the
upload. Nothing of the file itself is kept: no body, no file name (by the
third-party description it carries the client id), no client id, name, PAN
or account number. A batch keeps the file's SHA-256 and row counts only.

An opening lot (the user's own entry for shares bought before the file's
window) is a ``broker_fills`` row of ``kind = 'opening'`` with no batch.

Every fill of an imported book is posted into ``trades`` and ``positions``
by one rebuild (``services/imports/book.py``): ``broker_fills`` is the
source, ``trades`` (``trades.broker_fill_id``) its holdings-only ledger.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE
from stockviz.models.portfolio import BROKER_SQL

FILL_TRADE = "trade"
FILL_OPENING = "opening"

STATUS_POSTED = "posted"
STATUS_NEEDS_OPENING_LOT = "needs_opening_lot"

PRODUCT_DELIVERY = "delivery"
PRODUCT_INTRADAY = "intraday"
PRODUCT_MIXED = "mixed"

FEE_ESTIMATED = "estimated"

MAX_OPENING_LOTS_PER_BOOK = 500


class ImportBatch(SQLModel, table=True):
    """One committed upload. The file is never stored: only its hash and counts."""

    __tablename__ = "import_batches"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(f"broker IN ({BROKER_SQL})", name="ck_import_batches_broker"),
        Index("ix_import_batches_portfolio_created", "portfolio_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    broker: str = Field(sa_column=Column(String(16), nullable=False))
    # The column map the file was read with (``zerodha_tradebook_v1``).
    column_map: str = Field(sa_column=Column(String(40), nullable=False))
    file_sha256: str = Field(sa_column=Column(String(64), nullable=False))
    rows_total: int = Field(default=0, nullable=False)
    rows_added: int = Field(default=0, nullable=False)
    rows_duplicate: int = Field(default=0, nullable=False)
    rows_unmatched: int = Field(default=0, nullable=False)
    rows_skipped_segment: int = Field(default=0, nullable=False)
    rows_rejected: int = Field(default=0, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class BrokerFill(SQLModel, table=True):
    """One trade from a broker file (or an opening lot), as traded.

    ``quantity`` and ``price`` are never changed after the import; the
    posted ``trades`` row carries them restated for later splits.
    """

    __tablename__ = "broker_fills"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # Dedupe (design note): a trade id is assumed unique per exchange.
        # NULL trade ids (opening lots) never clash.
        UniqueConstraint(
            "portfolio_id", "broker", "exchange", "trade_id", name="uq_broker_fills_trade"
        ),
        CheckConstraint("kind IN ('trade', 'opening')", name="ck_broker_fills_kind"),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_broker_fills_side"),
        CheckConstraint("quantity > 0 AND price > 0", name="ck_broker_fills_quantity_price"),
        CheckConstraint("status IN ('posted', 'needs_opening_lot')", name="ck_broker_fills_status"),
        CheckConstraint(
            "(kind = 'opening') = (import_batch_id IS NULL)", name="ck_broker_fills_batch"
        ),
        Index("ix_broker_fills_portfolio_executed", "portfolio_id", "executed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    import_batch_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    kind: str = Field(default=FILL_TRADE, sa_column=Column(String(8), nullable=False))
    broker: str = Field(sa_column=Column(String(16), nullable=False))
    # NSE or BSE, as the file names the venue.
    exchange: str = Field(sa_column=Column(String(8), nullable=False))
    segment: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    series: str | None = Field(default=None, sa_column=Column(String(8), nullable=True))
    trade_id: str | None = Field(default=None, sa_column=Column(String(40), nullable=True))
    order_id: str | None = Field(default=None, sa_column=Column(String(40), nullable=True))
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    # The StockViz ticker the fill posts under (``RELIANCE.NS``).
    ticker: str = Field(sa_column=Column(String(16), nullable=False))
    isin: str | None = Field(default=None, sa_column=Column(String(12), nullable=True))
    raw_symbol: str | None = Field(default=None, sa_column=Column(String(40), nullable=True))
    side: str = Field(sa_column=Column(String(4), nullable=False))
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    # Naive UTC (the file's times are IST).
    executed_at: datetime = Field(nullable=False)
    # False when the file gave a date but no time: ``executed_at`` is then the
    # start of the trade date in IST, so a plan locks only if written before it.
    time_known: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )
    auction: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    # Set by every rebuild. Fees are estimated (the tradebook carries none).
    status: str = Field(
        default=STATUS_POSTED,
        sa_column=Column(String(20), nullable=False, server_default=STATUS_POSTED),
    )
    product: str | None = Field(default=None, sa_column=Column(String(10), nullable=True))
    fees: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6), nullable=True))
    fee_source: str | None = Field(default=None, sa_column=Column(String(12), nullable=True))
    fee_lines: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    )
    # The as-traded price falls outside the split-adjusted bar of its day
    # after restating: an unrecorded bonus, rights issue or split.
    basis_uncertain: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = [
    "FEE_ESTIMATED",
    "FILL_OPENING",
    "FILL_TRADE",
    "MAX_OPENING_LOTS_PER_BOOK",
    "PRODUCT_DELIVERY",
    "PRODUCT_INTRADAY",
    "PRODUCT_MIXED",
    "STATUS_NEEDS_OPENING_LOT",
    "STATUS_POSTED",
    "BrokerFill",
    "ImportBatch",
]
