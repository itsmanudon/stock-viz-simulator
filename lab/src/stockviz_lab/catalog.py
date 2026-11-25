"""``lab catalog`` and ``lab query``: a DuckDB file of views over the export.

Each table in the manifest becomes one view,
``read_parquet('<root>/<table>/**/*.parquet', hive_partitioning = true)``, so a
dated table also has ``year`` and ``month`` columns from its partition path.
Views hold absolute paths: move the export and run ``lab catalog`` again.
``_lab_catalog`` records the views this package made, so a refresh drops a
view whose table left the manifest and never touches anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb
import polars as pl

from stockviz_lab.manifest import load_manifest

DB_NAME = "lab.duckdb"
REGISTRY = "_lab_catalog"


@dataclass(frozen=True)
class CatalogRow:
    table: str
    rows: int
    manifest_rows: int
    min_date: date | None
    max_date: date | None

    @property
    def ok(self) -> bool:
        return self.rows == self.manifest_rows


def default_db(root: Path) -> Path:
    return root / DB_NAME


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _as_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def build_catalog(root: Path, db: Path | None = None) -> list[CatalogRow]:
    """Create or refresh the views; return each table's rows and date range."""
    manifest = load_manifest(root)
    root = root.resolve()
    con = duckdb.connect(str(db or default_db(root)))
    try:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {REGISTRY} ("
            "view_name VARCHAR PRIMARY KEY, source_glob VARCHAR, date_column VARCHAR, "
            "manifest_rows BIGINT, exported_at VARCHAR, refreshed_at TIMESTAMP)"
        )
        known = {r[0] for r in con.execute(f"SELECT view_name FROM {REGISTRY}").fetchall()}
        tables = manifest["tables"]
        for gone in sorted(known - set(tables)):
            con.execute(f"DROP VIEW IF EXISTS {_quote_ident(gone)}")
            con.execute(f"DELETE FROM {REGISTRY} WHERE view_name = ?", [gone])

        out: list[CatalogRow] = []
        for name, table in sorted(tables.items()):
            glob = str(root / name / "**" / "*.parquet")
            # Partition keys are integers ("month=01" would otherwise read as text).
            types = (
                ", hive_types = {'year': INTEGER, 'month': INTEGER}" if table["partitioned"] else ""
            )
            con.execute(
                f"CREATE OR REPLACE VIEW {_quote_ident(name)} AS SELECT * FROM "
                f"read_parquet({_quote_literal(glob)}, hive_partitioning = true{types})"
            )
            con.execute(
                f"INSERT OR REPLACE INTO {REGISTRY} VALUES (?, ?, ?, ?, ?, now()::TIMESTAMP)",
                [name, glob, table["date_column"], table["rows"], manifest["exported_at"]],
            )
            view = _quote_ident(name)
            column = table["date_column"]
            if column:
                col = _quote_ident(column)
                row = con.execute(f"SELECT count(*), min({col}), max({col}) FROM {view}").fetchone()
            else:
                row = con.execute(f"SELECT count(*), NULL, NULL FROM {view}").fetchone()
            assert row is not None
            out.append(
                CatalogRow(
                    table=name,
                    rows=int(row[0]),
                    manifest_rows=int(table["rows"]),
                    min_date=_as_date(row[1]),
                    max_date=_as_date(row[2]),
                )
            )
        return out
    finally:
        con.close()


def run_query(root: Path, sql: str, db: Path | None = None) -> pl.DataFrame:
    """Run ``sql`` read-only against the catalogue and return the result."""
    path = db or default_db(root.resolve())
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; run `lab catalog {root}` first")
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.sql(sql).pl()
    finally:
        con.close()
