"""The owner's intraday files loader (A6.1): formats, sessions, idempotency, the local guard.

Every file here is synthetic, written to ``tmp_path`` by the test: invented
prices on real session dates. No row of the owner's ``data/`` folder is used.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, text
from sqlmodel import Session, create_engine, select

from stockviz import cli
from stockviz.models import Instrument, IntradayBar, IntradayFile, Symbol
from stockviz.services.intraday.files import KINDS, ParseProblems, read_rows, ticker_for_stem
from stockviz.services.intraday.guard import (
    RemoteDatabaseRefused,
    local_database_problem,
    require_local_database,
)
from stockviz.services.intraday.load import files_in, load_files
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine
from tests.symbols import seed_symbols

HEADER = "date,open,high,low,close,volume"
IST = "+05:30"


def _minutes(day: str, start: str, count: int, *, offset: str | None = IST, volume: int = 100):
    """``count`` synthetic 1-minute rows from ``start`` (IST wall time) on ``day``."""
    base = datetime.fromisoformat(f"{day} {start}")
    rows = []
    for i in range(count):
        stamp = (base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        price = Decimal("100") + Decimal(i) / 10
        rows.append(
            f"{stamp}{offset or ''},{price},{price + 1},{price - 1},{price + Decimal('0.5')},{volume}"
        )
    return rows


def _write(path: Path, rows: list[str], crlf: bool = False) -> Path:
    path.write_text(("\r\n" if crlf else "\n").join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


# --- formats and names -----------------------------------------------------------


def test_ticker_mapping_from_file_names() -> None:
    assert ticker_for_stem("TCS") == "TCS.NS"
    assert ticker_for_stem("Nifty50") == "^NSEI"
    assert ticker_for_stem("NIFTY50") == "^NSEI"
    assert ticker_for_stem("BankNifty") == "BANKNIFTY.NS"
    assert ticker_for_stem("Sensex") == "^BSESN"


def test_discover_tells_the_kinds_apart(tmp_path: Path) -> None:
    for name in (
        "TCS_bulk_data.csv",
        "TCS_1hr_bulk_data.csv",
        "2025_TCS_1m_MoneyControl.csv",
        "notes.txt",
    ):
        _write(tmp_path / name, [])
    assert [p.name for p, _ in files_in(tmp_path, KINDS["bulk1m"])] == ["TCS_bulk_data.csv"]
    assert [p.name for p, _ in files_in(tmp_path, KINDS["bulk1h"])] == ["TCS_1hr_bulk_data.csv"]
    assert [t for _, t in files_in(tmp_path, KINDS["moneycontrol"])] == ["TCS.NS"]


def test_tz_aware_and_naive_ist_rows_map_to_the_same_utc_instant(tmp_path: Path) -> None:
    bulk = _write(tmp_path / "A_bulk_data.csv", _minutes("2025-11-25", "09:15", 2), crlf=True)
    mc = _write(
        tmp_path / "2025_A_1m_MoneyControl.csv", _minutes("2025-11-25", "09:15", 2, offset=None)
    )
    a = list(read_rows(bulk, KINDS["bulk1m"], ParseProblems()))
    b = list(read_rows(mc, KINDS["moneycontrol"], ParseProblems()))
    assert (
        [r.ts for r in a]
        == [r.ts for r in b]
        == [
            datetime(2025, 11, 25, 3, 45),
            datetime(2025, 11, 25, 3, 46),
        ]
    )
    assert a[0].open == Decimal("100")


def test_bulk_rows_without_an_offset_are_refused_not_guessed(tmp_path: Path) -> None:
    path = _write(tmp_path / "A_bulk_data.csv", _minutes("2025-11-25", "09:15", 3, offset=None))
    problems = ParseProblems()
    assert list(read_rows(path, KINDS["bulk1m"], problems)) == []
    assert problems.bad_time == 3


def test_impossible_and_unreadable_rows_are_rejected(tmp_path: Path) -> None:
    rows = [
        f"2025-11-25 09:15:00{IST},100,99,98,99,10",  # high below open
        f"2025-11-25 09:16:00{IST},100,101,99,100,-1",  # negative volume
        f"2025-11-25 09:17:00{IST},abc,101,99,100,1",
        f"not a date{IST},100,101,99,100,1",
        f"2025-11-25 09:18:00{IST},0,101,0,100,1",  # zero price
        f"2025-11-25 09:19:00{IST},100,101,99,100,5",
    ]
    problems = ParseProblems()
    good = list(read_rows(_write(tmp_path / "A_bulk_data.csv", rows), KINDS["bulk1m"], problems))
    assert len(good) == 1
    assert (problems.impossible, problems.negative_volume, problems.bad_number) == (2, 1, 1)
    assert problems.bad_time == 1
    assert problems.first_lines == [2, 3, 4, 5, 6]


# --- the local-only guard ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1:5454/x",
        "postgresql+psycopg://u:p@localhost/x",
        "postgresql+psycopg://u:p@[::1]:5432/x",
        "sqlite://",
    ],
)
def test_guard_allows_this_machine(url: str) -> None:
    assert local_database_problem(url) is None
    require_local_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@postgres.railway.internal:5432/railway",
        "postgresql+psycopg://u:p@shuttle.proxy.rlwy.net:41234/railway",
        "postgresql+psycopg://u:p@db.example.com/x",
        "postgresql+psycopg://u:p@10.0.0.5/x",
        "postgresql+psycopg://u:p@/x",  # no host: a socket or PGHOST decides
        "postgresql+psycopg://u:p@127.0.0.1/x?host=db.example.com",
        "postgresql+psycopg://u:p@localhost/x?hostaddr=10.0.0.5",
        "mysql://u:p@localhost/x",
    ],
)
def test_guard_refuses_everything_else(url: str) -> None:
    assert local_database_problem(url) is not None
    with pytest.raises(RemoteDatabaseRefused, match="There is no override"):
        require_local_database(url)


def test_loader_refuses_a_remote_database_before_reading_anything(tmp_path: Path) -> None:
    path = _write(tmp_path / "TCS_bulk_data.csv", _minutes("2025-11-25", "09:15", 3))
    remote = create_engine("postgresql+psycopg://u:p@postgres.railway.internal:5432/railway")
    with Session(remote) as session, pytest.raises(RemoteDatabaseRefused):
        # Dry run too: the loader never reads a remote database.
        load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=False)
    remote.dispose()


def test_cli_exits_2_for_a_remote_database_and_has_no_override(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _write(tmp_path / "TCS_bulk_data.csv", _minutes("2025-11-25", "09:15", 3))
    remote = create_engine("postgresql+psycopg://u:p@db.example.com:5432/prod")
    monkeypatch.setattr(cli, "engine", remote)
    code = cli.main(["intraday-load", "--dir", str(tmp_path), "--kind", "bulk1m", "--apply"])
    assert code == 2
    assert "refusing" in capsys.readouterr().out
    with pytest.raises(SystemExit):  # no flag exists to turn the guard off
        cli.main(["intraday-load", "--dir", str(tmp_path), "--kind", "bulk1m", "--force"])
    remote.dispose()


def test_production_config_never_runs_the_loader() -> None:
    railway = Path(__file__).resolve().parents[3] / ".railway" / "railway.ts"
    source = railway.read_text(encoding="utf-8")
    assert "intraday-load" not in source
    assert "intraday_bars" not in source


# --- loading -------------------------------------------------------------------


def _day_file(tmp_path: Path, name: str = "TCS_bulk_data.csv") -> Path:
    rows = (
        _minutes("2025-11-25", "09:14", 3)  # 09:14 is pre-open: off-session
        + _minutes("2025-11-25", "15:28", 3)  # 15:30 is past the close
        + _minutes("2023-11-12", "18:15", 2)  # Muhurat evening: in session
        + _minutes("2025-11-22", "10:00", 2)  # a Saturday: off-session
        + _minutes("2025-11-25", "10:00", 1)  # repeated below
        + _minutes("2025-11-25", "10:00", 1)
    )
    return _write(tmp_path / name, rows)


def test_session_filtering_duplicates_and_counts(session: Session, tmp_path: Path) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    path = _day_file(tmp_path)
    [report] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=False)
    assert report.rows_total == 12
    assert report.duplicate == 1
    assert report.off_session == 4  # 09:14, 15:30, two Saturday minutes
    assert report.accepted == 7
    assert report.sessions == 2
    assert sorted(d.isoformat() for d in report.off_session_days) == ["2025-11-22", "2025-11-25"]
    assert report.new == 7
    assert session.exec(select(func.count()).select_from(IntradayBar)).one() == 0  # dry run


def test_apply_is_idempotent_and_records_the_file(session: Session, tmp_path: Path) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    path = _day_file(tmp_path)
    [first] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=True)
    assert (first.status, first.inserted) == ("loaded", 7)
    [second] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=True)
    assert (second.status, second.inserted, second.already_stored) == ("loaded", 0, 7)
    assert session.exec(select(func.count()).select_from(IntradayBar)).one() == 7
    files = session.exec(select(IntradayFile)).all()
    assert len(files) == 1
    assert files[0].file_name == "TCS_bulk_data.csv"
    assert (files[0].rows_accepted, files[0].rows_off_session) == (7, 4)
    bars = session.exec(select(IntradayBar).order_by(IntradayBar.ts)).all()  # pyright: ignore[reportArgumentType]
    assert {b.feed for b in bars} == {"file"}
    assert {b.source for b in bars} == {"bulk_1m"}
    assert {b.interval for b in bars} == {"1m"}
    muhurat = bars[0]
    assert muhurat.ts == datetime(2023, 11, 12, 12, 45)
    assert muhurat.available_at == datetime(2023, 11, 12, 12, 46)
    assert muhurat.file_id == files[0].id


def test_hourly_bars_overlap_the_session_and_clip_availability(
    session: Session, tmp_path: Path
) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    rows = [f"2025-11-25 {h}:15:00{IST},100,101,99,100,10" for h in ("09", "10", "14", "15", "16")]
    path = _write(tmp_path / "TCS_1hr_bulk_data.csv", rows)
    [report] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1h"], apply=True)
    assert (report.accepted, report.off_session) == (4, 1)  # 16:15 is after the close
    last = session.exec(
        select(IntradayBar).where(IntradayBar.ts == datetime(2025, 11, 25, 9, 45))
    ).one()
    assert last.interval == "60m"
    assert last.available_at == datetime(2025, 11, 25, 10, 0)  # 15:30 IST, not 16:15


def test_minute_and_hour_bars_at_the_same_instant_both_store(
    session: Session, tmp_path: Path
) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    m = _write(tmp_path / "TCS_bulk_data.csv", _minutes("2025-11-25", "09:15", 1))
    h = _write(tmp_path / "TCS_1hr_bulk_data.csv", _minutes("2025-11-25", "09:15", 1))
    load_files(session, [(m, "TCS.NS")], KINDS["bulk1m"], apply=True)
    load_files(session, [(h, "TCS.NS")], KINDS["bulk1h"], apply=True)
    assert session.exec(select(func.count()).select_from(IntradayBar)).one() == 2


def test_unknown_ticker_is_reported_or_created(session: Session, tmp_path: Path) -> None:
    path = _write(
        tmp_path / "BANKNIFTY_bulk_data.csv", _minutes("2025-11-25", "09:15", 2, volume=0)
    )
    [dry] = load_files(
        session, [(path, "BANKNIFTY.NS")], KINDS["bulk1m"], apply=False, create_symbols=True
    )
    assert dry.status == "unmatched" and dry.would_create_symbol
    assert session.get(Symbol, "BANKNIFTY.NS") is None
    [plain] = load_files(session, [(path, "BANKNIFTY.NS")], KINDS["bulk1m"], apply=True)
    assert plain.status == "unmatched"
    [made] = load_files(
        session, [(path, "BANKNIFTY.NS")], KINDS["bulk1m"], apply=True, create_symbols=True
    )
    assert made.status == "loaded" and made.symbol_created and made.inserted == 2
    symbol = session.get(Symbol, "BANKNIFTY.NS")
    assert symbol is not None and symbol.currency == "INR"
    # An index: its zero volume is stored as 0 and the instrument says it is not real.
    assert made.is_index and made.nonzero_volume == 0
    asset = session.exec(select(Instrument.asset_type).where(Instrument.id == made.instrument_id))
    assert asset.one() == "index"


def test_moneycontrol_is_never_written(session: Session, tmp_path: Path) -> None:
    path = _write(tmp_path / "2025_TCS_1m_MoneyControl.csv", _minutes("2025-11-25", "09:15", 2))
    with pytest.raises(ValueError, match="reconciliation only"):
        load_files(session, [(path, "TCS.NS")], KINDS["moneycontrol"], apply=True)


# --- PostgreSQL: COPY, partitions -------------------------------------------------------

needs_pg = pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")


@needs_pg
def test_postgres_copy_path_partitions_and_idempotency(tmp_path: Path) -> None:
    from stockviz.services.intraday.size import measure

    with scratch_postgres_engine() as engine, Session(engine) as session:
        seed_symbols(session, "TCS.NS", currency="INR")
        rows = _minutes("2025-11-25", "09:15", 30) + _minutes("2025-12-01", "09:15", 30)
        path = _write(tmp_path / "TCS_bulk_data.csv", rows)
        [first] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=True)
        assert (first.status, first.inserted) == ("loaded", 60)
        [again] = load_files(session, [(path, "TCS.NS")], KINDS["bulk1m"], apply=True)
        assert (again.inserted, again.already_stored) == (0, 60)
        with engine.connect() as conn:
            parts = conn.execute(
                text(
                    "SELECT relid::regclass::text FROM pg_partition_tree('intraday_bars') "
                    "WHERE isleaf ORDER BY 1"
                )
            ).scalars()
            assert list(parts) == ["intraday_bars_y2025m11", "intraday_bars_y2025m12"]
            report = measure(conn)
        assert report.rows == 60 and report.partitions == 2
        assert report.per_symbol == [("TCS.NS", "1m", 60)]
        assert report.bytes_per_row is not None and report.bytes_per_row > 0
