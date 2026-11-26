"""A user's own tradebook column map (A6.11, M10.2): "Map columns yourself".

For a broker StockViz has no map for (a US broker, or an Indian broker's
file whose headers differ from the built-in map), the user picks which
header of their file is which field (trade date, execution time, symbol,
exchange, side, quantity, price, trade id, order id, ISIN) and saves it under
a name. ``services/imports/columns.custom_map`` turns a row into a
``ColumnMap``.

Only header names are kept: never a cell value, the file or its name.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow

MAX_IMPORT_MAPS_PER_USER = 20
IMPORT_MAP_NAME_MAX = 60
IMPORT_MAP_HEADER_MAX = 60


class ImportColumnMap(SQLModel, table=True):
    __tablename__ = "import_column_maps"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_import_column_maps_user_name"),
        CheckConstraint(
            "default_exchange IS NULL OR default_exchange IN ('NSE', 'BSE')",
            name="ck_import_column_maps_exchange",
        ),
        CheckConstraint(
            "date_order IN ('auto', 'day_first', 'month_first')",
            name="ck_import_column_maps_date_order",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    name: str = Field(sa_column=Column(String(IMPORT_MAP_NAME_MAX), nullable=False))
    # Field -> the header it reads (``{"symbol": "Ticker", ...}``).
    mapping: dict[str, str] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    # Indian rows without an exchange column use this one; null: none.
    default_exchange: str | None = Field(default=None, sa_column=Column(String(3), nullable=True))
    date_order: str = Field(
        default="auto", sa_column=Column(String(12), nullable=False, server_default="auto")
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = [
    "IMPORT_MAP_HEADER_MAX",
    "IMPORT_MAP_NAME_MAX",
    "MAX_IMPORT_MAPS_PER_USER",
    "ImportColumnMap",
]
