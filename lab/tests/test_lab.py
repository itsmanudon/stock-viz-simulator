"""``lab verify``, ``lab catalog`` and ``lab query`` on a tiny export built here.

The export is written the way ``stockviz.cli export-parquet`` writes one
(layout, zstd, manifest fields), with invented rows. No network, no API import.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stockviz_lab.catalog import build_catalog, default_db, run_query
from stockviz_lab.cli import main
from stockviz_lab.manifest import ManifestError, verify

BAR_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("instrument_id", pa.int64(), nullable=False),
        pa.field("ts", pa.timestamp("us"), nullable=False),
        pa.field("interval", pa.string(), nullable=False),
        pa.field("close", pa.decimal128(18, 6), nullable=False),
        pa.field("volume", pa.int64(), nullable=False),
    ]
)
INSTRUMENT_SCHEMA = pa.schema(
    [pa.field("id", pa.int64(), nullable=False), pa.field("symbol", pa.string(), nullable=False)]
)

# Closes with all six decimals in use: a float would not round-trip them all.
BARS: list[tuple[str, int, datetime, Decimal]] = [
    ("AAPL", 1, datetime(2025, 1, 30), Decimal("236.123457")),
    ("AAPL", 1, datetime(2025, 1, 31), Decimal("235.999999")),
    ("RELIANCE.NS", 2, datetime(2025, 1, 31), Decimal("1260.050001")),
    ("AAPL", 1, datetime(2025, 2, 3), Decimal("228.010203")),
    ("RELIANCE.NS", 2, datetime(2025, 2, 3), Decimal("1251.300000")),
    ("RELIANCE.NS", 2, datetime(2025, 2, 28), Decimal("1189.123456")),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(root: Path, rel: str, table: pa.Table) -> dict[str, Any]:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return {"path": rel, "rows": table.num_rows, "bytes": path.stat().st_size, "sha256": _sha(path)}


def build_export(root: Path) -> Path:
    parts: list[dict[str, Any]] = []
    for year, month in ((2025, 1), (2025, 2)):
        rows = [b for b in BARS if (b[2].year, b[2].month) == (year, month)]
        table = pa.Table.from_pylist(
            [
                {
                    "ticker": t,
                    "instrument_id": i,
                    "ts": ts,
                    "interval": "1d",
                    "close": c,
                    "volume": 10,
                }
                for t, i, ts, c in rows
            ],
            schema=BAR_SCHEMA,
        )
        entry = _write(root, f"price_bars/year={year}/month={month:02d}/part.parquet", table)
        dates = [r[2].date() for r in rows]
        entry |= {
            "year": year,
            "month": month,
            "min_date": min(dates).isoformat(),
            "max_date": max(dates).isoformat(),
        }
        parts.append(entry)
    instruments = pa.Table.from_pylist(
        [{"id": 1, "symbol": "AAPL"}, {"id": 2, "symbol": "RELIANCE"}], schema=INSTRUMENT_SCHEMA
    )
    inst = _write(root, "instruments/part.parquet", instruments) | {
        "min_date": None,
        "max_date": None,
    }
    manifest = {
        "schema_version": 1,
        "exported_at": "2026-11-25T12:00:00Z",
        "source_commit": "test",
        "since": None,
        "tables_requested": ["price_bars", "instruments"],
        "empty_tables": [],
        "tables": {
            "instruments": {
                "date_column": None,
                "partitioned": False,
                "filter": None,
                "columns": [],
                "rows": 2,
                "partitions": [inst],
            },
            "price_bars": {
                "date_column": "ts",
                "partitioned": True,
                "filter": "interval = '1d'",
                "columns": [],
                "rows": len(BARS),
                "partitions": parts,
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return root


@pytest.fixture
def export(tmp_path: Path) -> Path:
    return build_export(tmp_path / "export")


def test_verify_passes_on_an_intact_export(export: Path) -> None:
    report = verify(export)
    assert report.ok, report.problems
    assert (report.partitions, report.rows) == (3, len(BARS) + 2)
    assert main(["verify", str(export)]) == 0


def test_a_tampered_file_fails_verify(export: Path, capsys) -> None:
    target = export / "price_bars/year=2025/month=02/part.parquet"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0xFF
    target.write_bytes(bytes(data))
    report = verify(export)
    assert not report.ok
    assert any("month=02" in p and "sha256" in p for p in report.problems)
    assert main(["verify", str(export)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_a_wrong_row_count_missing_or_unlisted_file_fails(export: Path) -> None:
    manifest = json.loads((export / "manifest.json").read_text())
    manifest["tables"]["instruments"]["partitions"][0]["rows"] = 3
    (export / "manifest.json").write_text(json.dumps(manifest))
    (export / "price_bars/year=2025/month=01/part.parquet").unlink()
    extra = export / "price_bars/year=2024/month=12/part.parquet"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"not listed")
    problems = verify(export).problems
    assert any("instruments/part.parquet: 2 rows != manifest 3" in p for p in problems)
    assert any("month=01/part.parquet: missing" in p for p in problems)
    assert any("month=12/part.parquet: not in the manifest" in p for p in problems)


def test_an_unknown_schema_version_is_refused(export: Path) -> None:
    manifest = json.loads((export / "manifest.json").read_text())
    manifest["schema_version"] = 99
    (export / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ManifestError, match="99"):
        verify(export)
    assert main(["verify", str(export)]) == 1


def test_catalog_views_return_the_right_counts_and_ranges(export: Path) -> None:
    rows = {r.table: r for r in build_catalog(export)}
    assert rows["price_bars"].rows == len(BARS)
    assert (rows["price_bars"].min_date, rows["price_bars"].max_date) == (
        date(2025, 1, 30),
        date(2025, 2, 28),
    )
    assert rows["instruments"].rows == 2 and rows["instruments"].min_date is None
    assert all(r.ok for r in rows.values())
    con = duckdb.connect(str(default_db(export)), read_only=True)
    try:
        per_month = con.execute(
            "SELECT year, month, count(*) FROM price_bars GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        per_ticker = dict(
            con.execute("SELECT ticker, count(*) FROM price_bars GROUP BY 1").fetchall()
        )
    finally:
        con.close()
    assert per_month == [(2025, 1, 3), (2025, 2, 3)]
    assert per_ticker == {"AAPL": 3, "RELIANCE.NS": 3}


def test_catalog_refresh_drops_a_view_whose_table_left_the_manifest(export: Path) -> None:
    build_catalog(export)
    manifest = json.loads((export / "manifest.json").read_text())
    del manifest["tables"]["instruments"]
    (export / "manifest.json").write_text(json.dumps(manifest))
    assert [r.table for r in build_catalog(export)] == ["price_bars"]
    con = duckdb.connect(str(default_db(export)), read_only=True)
    try:
        views = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views()").fetchall()}
    finally:
        con.close()
    assert "instruments" not in views and "price_bars" in views


def test_decimals_round_trip_exactly(export: Path) -> None:
    build_catalog(export)
    frame = run_query(export, "SELECT ticker, ts, close FROM price_bars ORDER BY ticker, ts")
    assert str(frame.schema["close"]) == "Decimal(precision=18, scale=6)"
    got = [(r["ticker"], r["ts"], r["close"]) for r in frame.iter_rows(named=True)]
    assert got == sorted((t, ts, c) for t, _i, ts, c in BARS)
    con = duckdb.connect(str(default_db(export)), read_only=True)
    try:
        total = con.execute("SELECT sum(close) FROM price_bars").fetchone()
    finally:
        con.close()
    assert total is not None and total[0] == sum(c for *_x, c in BARS)


def test_query_prints_a_table_and_needs_a_catalog(export: Path, capsys) -> None:
    assert main(["query", str(export), "SELECT 1 AS one"]) == 1
    assert "run `lab catalog" in capsys.readouterr().out
    assert main(["catalog", str(export)]) == 0
    assert "price_bars" in capsys.readouterr().out
    sql = "SELECT ticker, count(*) AS bars FROM price_bars GROUP BY 1 ORDER BY 1"
    assert main(["query", str(export), sql]) == 0
    out = capsys.readouterr().out
    assert "AAPL" in out and "RELIANCE.NS" in out
