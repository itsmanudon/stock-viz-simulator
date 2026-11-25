"""What ``export-parquet`` exports (A1.6). No pyarrow here, so the CLI can list it cheaply."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Table
from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True)
class ExportTable:
    name: str
    # The date a dated table is partitioned by; None for a snapshot table.
    date_column: str | None
    order_by: tuple[str, ...]
    where: Callable[[Table], ColumnElement[bool]] | None = None
    where_sql: str | None = None  # the same filter, written into the manifest


def _daily(t: Table) -> ColumnElement[bool]:
    return t.c.interval == "1d"


TABLES: tuple[ExportTable, ...] = (
    ExportTable("price_bars", "ts", ("instrument_id", "ts"), _daily, "interval = '1d'"),
    ExportTable("eod_raw", "session_date", ("instrument_id", "session_date", "series")),
    ExportTable("eod_extras", "session_date", ("instrument_id", "session_date", "series")),
    ExportTable("corporate_actions", "ex_date", ("instrument_id", "ex_date", "id")),
    ExportTable("fundamental_facts", "available_at", ("instrument_id", "available_at", "id")),
    ExportTable("fx_rates", "date", ("currency", "date")),
    ExportTable("instruments", None, ("id",)),
    ExportTable("instrument_identifiers", None, ("instrument_id", "id")),
    ExportTable("data_files", None, ("id",)),
)
TABLE_NAMES = tuple(t.name for t in TABLES)
