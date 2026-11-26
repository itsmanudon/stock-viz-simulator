"""Paper-trading models: portfolios, positions, trades, daily snapshots.

All monetary values are ``Decimal`` so position math stays exact. Quantities
are also ``Decimal`` to leave room for fractional shares.
"""

from __future__ import annotations

import enum
from datetime import date as date_type
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
from stockviz.models.instrument import instrument_id_column


class TradeSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


IMPORT_BROKERS = ("zerodha", "dhan", "fyers", "upstox", "angelone", "groww", "other")
"""A5.3, A6.11: the brokers an imported book (and an import batch) names.
``other`` is a book read with the user's own column map (a US broker, say)."""
BROKER_SQL = ", ".join(f"'{b}'" for b in IMPORT_BROKERS)


class BookKind(enum.StrEnum):
    """A5.1: a paper book trades in the simulator; an imported one holds a
    broker's fills (A5.3) and never trades here."""

    PAPER = "paper"
    IMPORTED = "imported"


class HolderKind(enum.StrEnum):
    """Whose money a book stands for (A5.1, question 1). A label only: no PAN."""

    SELF = "self"
    FAMILY = "family"
    HUF = "huf"


MAX_BOOKS_PER_USER = 20
"""A5.1 cap on books per user, archived ones included (question 1)."""

BOOK_NAME_MAX = 60
HOLDER_LABEL_MAX = 60


class Portfolio(SQLModel, table=True):
    """One book (A5.1). A user holds up to ``MAX_BOOKS_PER_USER``; exactly one
    is the default, which every route uses when no ``?book=`` is given."""

    __tablename__ = "portfolios"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # Backstop for the portfolio lock (audit LG-11): every writer checks
        # available cash first, so a negative balance means a lost race.
        CheckConstraint("cash_balance >= 0", name="ck_portfolios_cash_nonnegative"),
        CheckConstraint("kind IN ('paper', 'imported')", name="ck_portfolios_kind"),
        CheckConstraint(
            "holder_kind IN ('self', 'family', 'huf')", name="ck_portfolios_holder_kind"
        ),
        CheckConstraint(f"broker IS NULL OR broker IN ({BROKER_SQL})", name="ck_portfolios_broker"),
        # The default book is the one writes fall back to: never archived.
        CheckConstraint(
            "NOT (is_default AND archived_at IS NOT NULL)",
            name="ck_portfolios_default_not_archived",
        ),
        # One default per user. Two concurrent first requests both try to
        # INSERT a default; the loser hits this index and re-reads the winner
        # (the race guard the old unique user_id index gave, kept per book).
        Index(
            "uq_portfolios_user_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
        UniqueConstraint("user_id", "name", name="uq_portfolios_user_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(default="Default", max_length=128)
    kind: BookKind = Field(
        default=BookKind.PAPER,
        sa_column=Column(String(16), nullable=False, server_default="paper"),
    )
    # Python default True: code that builds a lone Portfolio (tests, seeds)
    # gets the default book, as before A5.1. Book CRUD sets False.
    is_default: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    # False for an imported book: holdings only, cash stays 0 (A5.3).
    cash_tracked: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )
    broker: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    holder_kind: HolderKind = Field(
        default=HolderKind.SELF,
        sa_column=Column(String(8), nullable=False, server_default="self"),
    )
    # Free text ("Mum", "Jariwala HUF"). Never a PAN or account number.
    holder_label: str | None = Field(
        default=None, sa_column=Column(String(HOLDER_LABEL_MAX), nullable=True)
    )
    # Readable, never tradable, while set.
    archived_at: datetime | None = Field(default=None, nullable=True)
    # Cash in ``base_currency``. Other currencies live in ``cash_balances``
    # (Phase 4.5b): a sale of SAP.DE credits EUR, and a buy spends EUR first.
    cash_balance: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    # USD or INR, per book (Phase 4.8; A5.1 made it per book). Fixed once
    # the book has activity.
    base_currency: str = Field(
        default="USD", sa_column=Column(String(3), nullable=False, server_default="USD")
    )
    # The value the book started with, fixed for good (audit LG-1). Returns and
    # the leaderboard measure from it: the first snapshot can be overwritten by
    # the nightly job once the user trades on the opening day.
    opening_nav: Decimal = Field(
        default=Decimal(100_000),
        sa_column=Column(Numeric(20, 6), nullable=False, server_default="100000"),
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class CashBalance(SQLModel, table=True):
    """A portfolio's cash in one non-base currency (Phase 4.5b, option B).

    Written only by ``services/trading/cash.py``, under the portfolio row lock.
    """

    __tablename__ = "cash_balances"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("portfolio_id", "currency", name="uq_cash_balances_portfolio_currency"),
        CheckConstraint("amount >= 0", name="ck_cash_balances_nonnegative"),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    currency: str = Field(max_length=3)
    amount: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))


class FxConversion(SQLModel, table=True):
    """Cash moved between currencies, at the rate used (Phase 4.5b).

    A buy whose currency balance is short converts the shortfall from the base
    currency and records it here, so every conversion is on the ledger.
    """

    __tablename__ = "fx_conversions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "from_amount > 0 AND to_amount > 0 AND rate > 0", name="ck_fx_conversions_positive"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    trade_id: int | None = Field(default=None, foreign_key="trades.id", index=True)
    from_currency: str = Field(max_length=3)
    to_currency: str = Field(max_length=3)
    from_amount: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    to_amount: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    # Units of ``from_currency`` per one unit of ``to_currency`` (USD per EUR).
    rate: Decimal = Field(sa_column=Column(Numeric(18, 8), nullable=False))
    rate_date: date_type | None = None
    reason: str = Field(max_length=32)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Position(SQLModel, table=True):
    """Aggregated holding for one (portfolio, ticker).

    Maintained as a materialized roll-up of trades for fast portfolio reads.
    Written by ``services/trading/execute.py::apply_fill`` — the single fill
    path shared by market orders and pending-order settlement.
    """

    __tablename__ = "positions"  # pyright: ignore[reportAssignmentType]
    # One row per holding, never empty (audit LG-11). apply_fill deletes a
    # position sold to zero, and two racing first buys must not both insert.
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", name="uq_positions_portfolio_instrument"),
        CheckConstraint("quantity > 0", name="ck_positions_quantity_positive"),
        CheckConstraint("avg_cost >= 0", name="ck_positions_avg_cost_nonnegative"),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))

    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    avg_cost: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))


class Trade(SQLModel, table=True):
    __tablename__ = "trades"  # pyright: ignore[reportAssignmentType]
    # The Trading Journal scans one portfolio's fills over a month
    # (portfolio_id = ? AND ts >= ? AND ts < ?). The separate portfolio_id and
    # ts indexes each answer only half of that.
    __table_args__ = (
        Index("ix_trades_portfolio_ts", "portfolio_id", "ts"),
        # A repeated market order with the same client key returns the first
        # fill instead of filling twice (#67, audit LG-10). NULLs never clash.
        UniqueConstraint(
            "portfolio_id", "client_order_id", name="uq_trades_portfolio_client_order_id"
        ),
        CheckConstraint("quantity > 0 AND price > 0", name="ck_trades_quantity_price_positive"),
    )

    id: int | None = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))

    side: TradeSide = Field(max_length=8)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    ts: datetime = Field(default_factory=utcnow, nullable=False, index=True)

    # USD per one unit of the symbol's native currency, captured at fill time.
    # Persisting it means the trade log can show what the fill actually cost
    # instead of re-converting historical trades at today's rate. 1 for USD
    # symbols; NULL only on rows written before this column existed.
    fx_rate: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 8), nullable=True))
    # Realized P&L in USD against the position's weighted-average cost basis.
    # Set on sells; NULL on buys (a buy realizes nothing).
    realized_pnl: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 6), nullable=True)
    )
    # Native weighted-average basis captured before a sell mutates holdings.
    avg_cost_at_fill: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    # Client-generated key for a market order (POST /v1/trades). NULL on fills
    # from pending orders, option exercise and rows written before it existed.
    client_order_id: str | None = Field(default=None, max_length=64, nullable=True)
    # A4.2: fees charged on this fill, in the symbol's currency, from the
    # date-versioned schedule in force on the fill date
    # (``services/simulation/fees.py``). Buys pay them on top of the price,
    # sells net them from the proceeds; ``realized_pnl`` stays the price
    # gain (gross). NULL on rows written before A4.2 (never recalculated).
    fees: Decimal | None = Field(default=None, sa_column=Column(Numeric(20, 6), nullable=True))
    fee_schedule: str | None = Field(default=None, max_length=40, nullable=True)
    # [{key, label, amount, rate, side, effective_from, source_url}] per component.
    fee_lines: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    )
    # A5.4: the plan this fill belongs to (``trade_plans``; null = none).
    trade_plan_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("trade_plans.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    # A5.3: the broker fill (``broker_fills``) an imported book's trade posts.
    # Null for paper fills. Its quantity and price are restated for splits
    # after the fill; the broker fill keeps them as traded.
    broker_fill_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("broker_fills.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
    )


class PortfolioSnapshot(SQLModel, table=True):
    """One row per book per day with the book's net asset value.

    Written by an APScheduler job after the daily price refresh. The
    ``(portfolio_id, date)`` uniqueness (A5.1; it was per user) lets the
    writer use upsert / idempotent re-runs without piling up duplicates.
    ``user_id`` stays for the combined view across a user's books (A5.2).
    """

    __tablename__ = "portfolio_snapshots"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("portfolio_id", "date", name="uq_portfolio_snapshots_portfolio_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    portfolio_id: int = Field(foreign_key="portfolios.id", index=True)
    date: date_type = Field(nullable=False, index=True)
    nav: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
