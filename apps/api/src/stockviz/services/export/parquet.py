"""Parquet export for the research node (A1.6, M1.8).

``stockviz.cli export-parquet --out DIR`` writes the spine tables as zstd
Parquet under ``DIR`` with a ``manifest.json``, for the laptop's ``lab/``
package (DuckDB) to read. Layout:

- tables with a date (``DATED``): one file per calendar month of that date,
  ``<table>/year=YYYY/month=MM/part.parquet`` (Hive-style, so DuckDB reads
  the partition keys);
- small reference tables (``SNAPSHOT``): the whole table as
  ``<table>/part.parquet``, rewritten on every run.

Rules:

- Prices stay exact: ``Numeric(p, s)`` columns are Parquet ``decimal(p, s)``,
  never float. Timestamps are naive UTC, as stored.
- Rows are read in chunks of ``CHUNK_ROWS`` through a streaming cursor, one
  month at a time, ordered by instrument then date; nothing loads a whole
  table.
- Each file is written to a hidden temporary name beside it and renamed into
  place, so a failure never leaves a partial ``part.parquet``. The manifest is
  written the same way, last.
- ``since`` re-exports only the months on or after the month of ``since``;
  older partitions are kept as they are (not rewritten) with their manifest
  entries. A row inserted later with an older date (a late restatement) is
  only picked up by a full export. A month that has become empty is removed.
- A table with no rows is skipped and reported. Files a previous manifest
  listed that this run does not rewrite are deleted; nothing else in ``DIR``
  is touched.
- ``data_files`` is exported as metadata only: the raw files themselves stay
  in ``NSE_ARCHIVE_DIR``.

The manifest records the schema version, export time, source commit and,
per partition, the row count, size, SHA-256 and min/max date. Bump
``EXPORT_SCHEMA_VERSION`` when the layout or a table's columns change
meaningfully; a ``since`` run against a manifest of another version, or a
table whose columns changed, exports that table in full.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    TypeDecorator,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel

import stockviz.models  # noqa: F401 - register every table on the metadata
from stockviz.services.export.tables import TABLE_NAMES, TABLES, ExportTable

EXPORT_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
PART_NAME = "part.parquet"
CHUNK_ROWS = 50_000
COMPRESSION = "zstd"


class ExportError(RuntimeError):
    pass


@dataclass
class TableReport:
    name: str
    status: str  # exported | empty
    rows_written: int = 0
    partitions_written: int = 0
    partitions_kept: int = 0
    partitions_removed: int = 0
    full: bool = True


@dataclass
class ExportReport:
    out: Path
    manifest: dict[str, Any]
    tables: list[TableReport] = field(default_factory=list)


# --- types -------------------------------------------------------------------


def arrow_type(column_type: Any) -> pa.DataType:
    """The Parquet type for a SQLAlchemy column type. Decimals stay decimals."""
    while isinstance(column_type, TypeDecorator):  # SQLModel's AutoString
        column_type = column_type.impl
    if isinstance(column_type, Numeric) and not isinstance(column_type, Integer):
        precision = column_type.precision or 38
        scale = column_type.scale or 0
        return pa.decimal128(precision, scale)
    if isinstance(column_type, Integer):
        return pa.int64()
    if isinstance(column_type, Boolean):
        return pa.bool_()
    if isinstance(column_type, DateTime):
        return pa.timestamp("us")
    if isinstance(column_type, Date):
        return pa.date32()
    if isinstance(column_type, String | Text):
        return pa.string()
    raise ExportError(f"no Parquet type for column type {column_type!r}")


def arrow_schema(table: Table) -> pa.Schema:
    return pa.schema(
        [pa.field(c.name, arrow_type(c.type), nullable=bool(c.nullable)) for c in table.columns]
    )


def _columns_of(schema: pa.Schema) -> list[dict[str, str]]:
    return [{"name": f.name, "type": str(f.type)} for f in schema]


# --- helpers -----------------------------------------------------------------


def source_commit() -> str:
    """``RAILWAY_GIT_COMMIT_SHA``, else ``git rev-parse HEAD``, else ``unknown``."""
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _months(first: date, last: date) -> Iterator[date]:
    month = _month_start(first)
    while month <= last:
        yield month
        month = _next_month(month)


def partition_path(table: str, month: date | None) -> str:
    if month is None:
        return f"{table}/{PART_NAME}"
    return f"{table}/year={month.year:04d}/month={month.month:02d}/{PART_NAME}"


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        _fsync(tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def write_parquet_atomic(dest: Path, schema: pa.Schema, batches: Iterable[pa.Table]) -> int | None:
    """Write ``batches`` to ``dest`` via a temporary file; return the row count.

    Returns None (and writes nothing) when there were no rows. On any error the
    temporary file is removed and ``dest`` is left as it was.
    """
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    writer: pq.ParquetWriter | None = None
    rows = 0
    try:
        for batch in batches:
            if batch.num_rows == 0:
                continue
            if writer is None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                writer = pq.ParquetWriter(tmp, schema, compression=COMPRESSION)
            writer.write_table(batch)
            rows += batch.num_rows
        if writer is None:
            return None
        writer.close()
        writer = None
        _fsync(tmp)
        os.replace(tmp, dest)
        return rows
    finally:
        if writer is not None:
            writer.close()
        tmp.unlink(missing_ok=True)


def load_manifest(out: Path) -> dict[str, Any] | None:
    path = out / MANIFEST_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --- the export ----------------------------------------------------------------


def _chunks_to_tables(
    rows: Iterable[Sequence[Sequence[Any]]],
    schema: pa.Schema,
    date_column: str | None,
    bounds: list[date],
) -> Iterator[pa.Table]:
    """Turn row chunks into Arrow tables; keep the date column's [min, max] in ``bounds``."""
    names = schema.names
    date_index = names.index(date_column) if date_column is not None else None
    for chunk in rows:
        if not chunk:
            continue
        columns = list(zip(*chunk, strict=True))
        arrays = [
            pa.array(list(values), type=schema.field(i).type) for i, values in enumerate(columns)
        ]
        if date_index is not None:
            dates = [_as_date(v) for v in columns[date_index] if v is not None]
            if dates:
                lo, hi = min(dates), max(dates)
                if not bounds:
                    bounds.extend([lo, hi])
                else:
                    bounds[0], bounds[1] = min(bounds[0], lo), max(bounds[1], hi)
        yield pa.Table.from_arrays(arrays, schema=schema)


def _write_one(
    engine: Engine,
    spec: ExportTable,
    table: Table,
    schema: pa.Schema,
    out: Path,
    month: date | None,
) -> dict[str, Any] | None:
    stmt = select(*table.columns)
    conditions: list[ColumnElement[bool]] = []
    if spec.where is not None:
        conditions.append(spec.where(table))
    if month is not None and spec.date_column is not None:
        col = table.c[spec.date_column]
        lo: date | datetime = month
        hi: date | datetime = _next_month(month)
        if isinstance(col.type, DateTime):
            lo = datetime(month.year, month.month, 1)
            nxt = _next_month(month)
            hi = datetime(nxt.year, nxt.month, 1)
        conditions += [col >= lo, col < hi]
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(*(table.c[n] for n in spec.order_by))

    rel = partition_path(spec.name, month)
    dest = out / rel
    bounds: list[date] = []
    with engine.connect() as conn:
        result = conn.execution_options(stream_results=True, yield_per=CHUNK_ROWS).execute(stmt)
        rows = write_parquet_atomic(
            dest,
            schema,
            _chunks_to_tables(result.partitions(CHUNK_ROWS), schema, spec.date_column, bounds),
        )
    if rows is None:
        return None
    entry: dict[str, Any] = {
        "path": rel,
        "rows": rows,
        "bytes": dest.stat().st_size,
        "sha256": sha256_file(dest),
        "min_date": bounds[0].isoformat() if bounds else None,
        "max_date": bounds[1].isoformat() if bounds else None,
    }
    if month is not None:
        entry["year"] = month.year
        entry["month"] = month.month
    return entry


def _date_range(engine: Engine, spec: ExportTable, table: Table) -> tuple[date, date] | None:
    assert spec.date_column is not None
    col = table.c[spec.date_column]
    stmt = select(func.min(col), func.max(col))
    if spec.where is not None:
        stmt = stmt.where(spec.where(table))
    with engine.connect() as conn:
        lo, hi = conn.execute(stmt).one()
    if lo is None or hi is None:
        return None
    return _as_date(lo), _as_date(hi)


def _has_rows(engine: Engine, table: Table) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one() > 0


def _remove(out: Path, rel: str) -> None:
    (out / rel).unlink(missing_ok=True)


def export_parquet(
    engine: Engine,
    out: Path,
    *,
    since: date | None = None,
    tables: Sequence[str] | None = None,
    now: datetime | None = None,
    commit: str | None = None,
) -> ExportReport:
    """Export the spine tables to ``out``. See the module docstring for the rules."""
    unknown = set(tables or ()) - set(TABLE_NAMES)
    if unknown:
        raise ExportError(f"unknown table(s): {', '.join(sorted(unknown))}")
    selected = [t for t in TABLES if tables is None or t.name in tables]
    out.mkdir(parents=True, exist_ok=True)

    previous = load_manifest(out)
    # Every file a previous manifest listed may be replaced or removed; only a
    # manifest of this schema version can keep partitions or other tables.
    listed: dict[str, Any] = dict((previous or {}).get("tables") or {})
    compatible = previous is not None and previous.get("schema_version") == EXPORT_SCHEMA_VERSION
    old_tables: dict[str, Any] = listed if compatible else {}
    since_month = _month_start(since) if since is not None else None

    report = ExportReport(out=out, manifest={})
    new_tables: dict[str, Any] = dict(old_tables)
    empty: list[str] = []

    for spec in selected:
        table = SQLModel.metadata.tables[spec.name]
        schema = arrow_schema(table)
        columns = _columns_of(schema)
        old = old_tables.get(spec.name)
        old_parts: list[dict[str, Any]] = list(listed.get(spec.name, {}).get("partitions", []))
        incremental = (
            since_month is not None
            and spec.date_column is not None
            and old is not None
            and old.get("columns") == columns
        )
        tr = TableReport(name=spec.name, status="exported", full=not incremental)

        kept: list[dict[str, Any]] = []
        written: list[dict[str, Any]] = []
        if spec.date_column is None:
            if _has_rows(engine, table):
                entry = _write_one(engine, spec, table, schema, out, None)
                if entry is not None:
                    written.append(entry)
        else:
            span = _date_range(engine, spec, table)
            if span is not None:
                first, last = span
                if incremental:
                    assert since_month is not None
                    kept = [p for p in old_parts if date(p["year"], p["month"], 1) < since_month]
                    first = max(first, since_month)
                for month in _months(first, last) if first <= last else ():
                    entry = _write_one(engine, spec, table, schema, out, month)
                    if entry is not None:
                        written.append(entry)

        live = {p["path"] for p in kept} | {p["path"] for p in written}
        for part in old_parts:
            if part["path"] not in live:
                _remove(out, part["path"])
                tr.partitions_removed += 1

        tr.partitions_written = len(written)
        tr.partitions_kept = len(kept)
        tr.rows_written = sum(p["rows"] for p in written)
        parts = sorted(kept + written, key=lambda p: p["path"])
        if not parts:
            tr.status = "empty"
            empty.append(spec.name)
            new_tables.pop(spec.name, None)
        else:
            new_tables[spec.name] = {
                "date_column": spec.date_column,
                "partitioned": spec.date_column is not None,
                "filter": spec.where_sql,
                "columns": columns,
                "rows": sum(p["rows"] for p in parts),
                "partitions": parts,
            }
        report.tables.append(tr)

    stamp = now or datetime.now(UTC)
    # Naive means UTC here, as everywhere in this codebase (``_time.utcnow``).
    stamp = (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)).replace(
        microsecond=0
    )
    manifest: dict[str, Any] = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": stamp.isoformat().replace("+00:00", "Z"),
        "source_commit": commit if commit is not None else source_commit(),
        "since": since.isoformat() if since is not None else None,
        "tables_requested": [t.name for t in selected],
        "empty_tables": empty,
        "tables": dict(sorted(new_tables.items())),
    }
    write_atomic_bytes(
        out / MANIFEST_NAME, (json.dumps(manifest, indent=2, sort_keys=False) + "\n").encode()
    )
    report.manifest = manifest
    return report


def inside_unignored_worktree(out: Path) -> bool:
    """True when ``out`` sits in a git work tree and git would not ignore it.

    Exports hold exchange data, which is never committed. Best effort: without
    git, or outside a work tree, this is False.
    """
    probe = out.resolve()
    parent = probe
    while not parent.exists():
        parent = parent.parent
    try:
        top = subprocess.run(
            ["git", "-C", str(parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if top.returncode != 0:
            return False
        ignored = subprocess.run(
            ["git", "-C", top.stdout.strip(), "check-ignore", "-q", str(probe / MANIFEST_NAME)],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return ignored.returncode != 0
