"""Parquet export for the research node (A1.6, M1.8): ``stockviz.cli export-parquet``.

Invented rows on SQLite (and scratch PostgreSQL when ``DATABASE_URL`` is one).
Nothing touches the network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import delete
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import FxRate, PriceBar
from stockviz.services.export import parquet
from stockviz.services.export.parquet import (
    EXPORT_SCHEMA_VERSION,
    ExportError,
    export_parquet,
    inside_unignored_worktree,
    source_commit,
)
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine
from tests.symbols import seed_symbols

NOW = datetime(2026, 11, 25, 12, 0, 0)
# Six decimals in use: a float would not carry them all.
CLOSES = {
    ("AAPL", date(2025, 1, 30)): Decimal("236.123457"),
    ("AAPL", date(2025, 1, 31)): Decimal("235.999999"),
    ("MSFT", date(2025, 1, 31)): Decimal("415.060001"),
    ("AAPL", date(2025, 2, 3)): Decimal("228.010203"),
    ("MSFT", date(2025, 2, 3)): Decimal("410.370000"),
    ("MSFT", date(2025, 2, 28)): Decimal("396.990001"),
}


def _bar(ticker: str, day: date, close: Decimal, interval: str = "1d") -> PriceBar:
    return PriceBar(
        ticker=ticker,
        ts=datetime(day.year, day.month, day.day),
        interval=interval,
        open=close,
        high=close + Decimal("1.000001"),
        low=close - Decimal("1.000001"),
        close=close,
        volume=1_000_000,
        source="yfinance",
    )


def _seed(session: Session) -> None:
    seed_symbols(session, "AAPL", "MSFT")
    for (ticker, day), close in CLOSES.items():
        session.add(_bar(ticker, day, close))
    # Not daily: never exported.
    session.add(_bar("AAPL", date(2025, 2, 7), Decimal("1.5"), interval="1wk"))
    session.add(FxRate(currency="INR", date=date(2025, 1, 31), usd_rate=Decimal("0.01155321")))
    session.add(FxRate(currency="INR", date=date(2025, 2, 3), usd_rate=Decimal("0.01149987")))
    session.commit()


def _export(engine, out: Path, **kwargs):
    return export_parquet(engine, out, now=NOW, commit="abc123", **kwargs)


def _read_all(folder: Path) -> pa.Table:
    return pa.concat_tables(pq.read_table(p) for p in sorted(folder.rglob("*.parquet")))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


JAN = "price_bars/year=2025/month=01/part.parquet"
FEB = "price_bars/year=2025/month=02/part.parquet"
MAR = "price_bars/year=2025/month=03/part.parquet"


@pytest.fixture
def seeded(engine, session: Session):
    _seed(session)
    return engine


def test_partitions_by_month_with_an_exact_manifest(seeded, tmp_path: Path) -> None:
    out = tmp_path / "export"
    report = _export(seeded, out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest == report.manifest
    assert manifest["schema_version"] == EXPORT_SCHEMA_VERSION
    assert manifest["exported_at"] == "2026-11-25T12:00:00Z"
    assert manifest["source_commit"] == "abc123"
    assert manifest["since"] is None

    bars = manifest["tables"]["price_bars"]
    assert bars["date_column"] == "ts" and bars["filter"] == "interval = '1d'"
    assert bars["rows"] == len(CLOSES)
    assert [p["path"] for p in bars["partitions"]] == [JAN, FEB]
    jan, feb = bars["partitions"]
    assert (jan["rows"], jan["min_date"], jan["max_date"]) == (3, "2025-01-30", "2025-01-31")
    assert (feb["rows"], feb["min_date"], feb["max_date"]) == (3, "2025-02-03", "2025-02-28")
    for part in bars["partitions"]:
        path = out / part["path"]
        assert part["sha256"] == _sha(path)
        assert part["bytes"] == path.stat().st_size
        assert pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD"

    fx = manifest["tables"]["fx_rates"]
    assert [p["path"] for p in fx["partitions"]] == [
        "fx_rates/year=2025/month=01/part.parquet",
        "fx_rates/year=2025/month=02/part.parquet",
    ]
    instruments = manifest["tables"]["instruments"]
    assert instruments["partitioned"] is False
    assert [p["path"] for p in instruments["partitions"]] == ["instruments/part.parquet"]
    assert instruments["partitions"][0]["min_date"] is None
    assert set(manifest["tables"]) == {
        "price_bars",
        "fx_rates",
        "instruments",
        "instrument_identifiers",
    }
    assert manifest["empty_tables"] == [
        "eod_raw",
        "eod_extras",
        "corporate_actions",
        "fundamental_facts",
        "data_files",
        "intraday_bars",
        "intraday_files",
    ]
    assert not (out / "eod_raw").exists()
    assert {t.name: t.status for t in report.tables}["eod_raw"] == "empty"
    assert not list(out.rglob("*.tmp"))


def test_decimals_are_parquet_decimals_and_exact(seeded, tmp_path: Path) -> None:
    out = tmp_path / "export"
    _export(seeded, out)
    table = _read_all(out / "price_bars")
    assert table.schema.field("close").type == pa.decimal128(18, 6)
    assert table.schema.field("volume").type == pa.int64()
    assert table.schema.field("ts").type == pa.timestamp("us")
    got = {(r["ticker"], r["ts"].date()): r["close"] for r in table.to_pylist()}
    assert got == CLOSES
    assert all(isinstance(v, Decimal) for v in got.values())
    rates = pq.read_table(out / "fx_rates/year=2025/month=01/part.parquet")
    assert rates.schema.field("usd_rate").type == pa.decimal128(18, 8)
    assert rates.column("usd_rate").to_pylist() == [Decimal("0.01155321")]


def test_since_rewrites_only_later_months(seeded, session: Session, tmp_path: Path) -> None:
    out = tmp_path / "export"
    _export(seeded, out)
    jan_path = out / JAN
    jan_before = (jan_path.stat().st_mtime_ns, _sha(jan_path))
    first = json.loads((out / "manifest.json").read_text())

    # A new March bar and a changed February bar.
    session.add(_bar("AAPL", date(2025, 3, 3), Decimal("238.030303")))
    feb_bar = session.exec(select(PriceBar).where(col(PriceBar.ts) == datetime(2025, 2, 28))).one()
    feb_bar.close = Decimal("397.000001")
    session.commit()

    report = _export(seeded, out, since=date(2025, 2, 15))
    manifest = report.manifest
    bars = manifest["tables"]["price_bars"]
    assert [p["path"] for p in bars["partitions"]] == [JAN, FEB, MAR]
    assert bars["partitions"][0] == first["tables"]["price_bars"]["partitions"][0]
    assert (jan_path.stat().st_mtime_ns, _sha(jan_path)) == jan_before
    assert bars["rows"] == len(CLOSES) + 1
    pb = next(t for t in report.tables if t.name == "price_bars")
    assert (pb.full, pb.partitions_written, pb.partitions_kept) == (False, 2, 1)
    feb = pq.read_table(out / FEB).to_pylist()
    assert Decimal("397.000001") in {r["close"] for r in feb}
    assert manifest["since"] == "2025-02-15"
    for part in bars["partitions"]:
        assert part["sha256"] == _sha(out / part["path"])

    # March empties again: the next incremental run removes its partition.
    session.execute(delete(PriceBar).where(col(PriceBar.ts) == datetime(2025, 3, 3)))
    session.commit()
    again = _export(seeded, out, since=date(2025, 3, 1))
    assert [p["path"] for p in again.manifest["tables"]["price_bars"]["partitions"]] == [JAN, FEB]
    assert not (out / MAR).exists()


def test_since_without_a_compatible_manifest_exports_in_full(seeded, tmp_path: Path) -> None:
    out = tmp_path / "export"
    _export(seeded, out)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["schema_version"] = EXPORT_SCHEMA_VERSION + 1
    (out / "manifest.json").write_text(json.dumps(manifest))
    report = _export(seeded, out, since=date(2025, 2, 1))
    pb = next(t for t in report.tables if t.name == "price_bars")
    assert pb.full and pb.partitions_written == 2
    assert report.manifest["schema_version"] == EXPORT_SCHEMA_VERSION


def test_a_table_subset_keeps_the_other_tables(seeded, tmp_path: Path) -> None:
    out = tmp_path / "export"
    _export(seeded, out)
    report = _export(seeded, out, tables=["fx_rates"])
    assert [t.name for t in report.tables] == ["fx_rates"]
    assert "price_bars" in report.manifest["tables"]
    with pytest.raises(ExportError, match="nope"):
        _export(seeded, out, tables=["nope"])


def test_a_failed_write_leaves_no_partial_file(seeded, tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "export"
    _export(seeded, out)
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}

    real = parquet._chunks_to_tables

    def broken(rows, schema, date_column, bounds):
        for table in real(rows, schema, date_column, bounds):
            yield table
            raise OSError("disk full")

    monkeypatch.setattr(parquet, "_chunks_to_tables", broken)
    with pytest.raises(OSError, match="disk full"):
        _export(seeded, out)
    after = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert after == before  # old partitions and manifest untouched, no temp files


def test_cli_exports_and_reports_empty_tables(seeded, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", seeded)
    out = tmp_path / "export"
    assert cli.main(["export-parquet", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "eod_raw: empty, skipped" in text
    assert "price_bars (full): wrote 2 partition(s), 6 rows" in text
    assert cli.main(["export-parquet", "--out", str(out), "--since", "2025-02-01"]) == 0
    assert "price_bars (since 2025-02-01): wrote 1 partition(s)" in capsys.readouterr().out
    assert "export-parquet" not in cli.RECORDED_JOBS


def test_intraday_bars_export_by_month_with_exact_decimals(
    seeded, session: Session, tmp_path: Path
) -> None:
    """A6.1: intraday bars go to the lake by month of the bar's open, decimals exact."""
    from stockviz.services.intraday.files import KINDS
    from stockviz.services.intraday.load import load_files

    seed_symbols(session, "TCS.NS", currency="INR")
    src = tmp_path / "TCS_bulk_data.csv"
    src.write_text(
        "date,open,high,low,close,volume\n"
        "2025-01-31 15:29:00+05:30,100.123456,101,99,100.5,7\n"
        "2025-02-03 09:15:00+05:30,100,101,99,100.25,8\n",
        encoding="utf-8",
    )
    load_files(session, [(src, "TCS.NS")], KINDS["bulk1m"], apply=True)
    out = tmp_path / "export"
    report = _export(seeded, out, tables=["intraday_bars", "intraday_files"])
    bars = report.manifest["tables"]["intraday_bars"]
    assert [p["path"] for p in bars["partitions"]] == [
        "intraday_bars/year=2025/month=01/part.parquet",
        "intraday_bars/year=2025/month=02/part.parquet",
    ]
    table = _read_all(out / "intraday_bars")
    assert table.schema.field("open").type == pa.decimal128(18, 6)
    assert table.column("open").to_pylist()[0] == Decimal("100.123456")
    assert table.column("ts").to_pylist()[0] == datetime(2025, 1, 31, 9, 59)
    assert report.manifest["tables"]["intraday_files"]["rows"] == 1


def test_cli_refuses_an_unignored_path_in_the_repository(seeded, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", seeded)
    inside = Path(__file__).resolve().parent / "export-parquet-should-not-exist"
    if not inside_unignored_worktree(inside):
        pytest.skip("not inside a git work tree")
    assert cli.main(["export-parquet", "--out", str(inside)]) == 1
    assert "refusing" in capsys.readouterr().out
    assert not inside.exists()
    ignored = Path(__file__).resolve().parents[3] / "lab" / "data" / "export"
    assert not inside_unignored_worktree(ignored)


def test_source_commit_prefers_railway(monkeypatch) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeef")
    assert source_commit() == "deadbeef"


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_postgres_export_is_exact_and_streams(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(parquet, "CHUNK_ROWS", 2)  # several chunks per partition
    with scratch_postgres_engine() as engine, Session(engine) as session:
        _seed(session)
        out = tmp_path / "export"
        report = export_parquet(engine, out, now=NOW, commit="pg")
        bars = report.manifest["tables"]["price_bars"]
        assert [p["rows"] for p in bars["partitions"]] == [3, 3]
        table = _read_all(out / "price_bars")
        got = {(r["ticker"], r["ts"].date()): r["close"] for r in table.to_pylist()}
        assert got == CLOSES
        assert pq.ParquetFile(out / JAN).metadata.num_row_groups == 2
