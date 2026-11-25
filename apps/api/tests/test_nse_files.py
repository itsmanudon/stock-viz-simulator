"""NSE end-of-day files (A1.1): parsers, date check, archive, loader, CLI.

Fixtures in ``tests/fixtures/nse/`` carry NSE's real headers and invented
rows (see the README there). Nothing here touches the network.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import DataFile, EodExtras, EodRaw, InstrumentIdentifier
from stockviz.models.instrument import SCHEME_ISIN
from stockviz.services.instruments import instrument_ids
from stockviz.services.nse.formats import (
    FileFormat,
    ParseError,
    UnrecognisedFile,
    date_from_file_name,
    read_bytes_as_text,
)
from stockviz.services.nse.load import LOAD_SERIES, apply_load, plan_load
from stockviz.services.nse.parse import check_date, parse_any, parse_cm, parse_sec_full
from stockviz.services.nse.process import ALREADY_RECORDED, process_file
from stockviz.settings import get_settings
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine
from tests.symbols import seed_symbols

FIXTURES = Path(__file__).parent / "fixtures" / "nse"
UDIFF = FIXTURES / "BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv"
LEGACY = FIXTURES / "cm05JUL2024bhav.csv"
SEC = FIXTURES / "sec_bhavdata_full_01012025.csv"
NSE_TICKERS = ("RELIANCE.NS", "TCS.NS", "SMEDEMO.NS", "20MICRONS.NS")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _zip(folder: Path, name: str, members: dict[str, str]) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, text in members.items():
            archive.writestr(member, text)
    return path


def _reshuffle(text: str) -> str:
    """The same table with its columns in reverse order and lower-case names."""
    rows = list(csv.reader(io.StringIO(text)))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    for i, row in enumerate(rows):
        cells = list(reversed(row))
        writer.writerow([c.lower() for c in cells] if i == 0 else cells)
    return out.getvalue()


def _redate_legacy(day: str) -> str:
    return _text(LEGACY).replace("05-JUL-2024", day)


@pytest.fixture
def nse(session: Session) -> Session:
    seed_symbols(session, *NSE_TICKERS, currency="INR")
    return session


@pytest.fixture
def archive(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    root = tmp_path / "archive"
    monkeypatch.setenv("NSE_ARCHIVE_DIR", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


def _iid(session: Session, ticker: str) -> int:
    return instrument_ids(session, [ticker])[ticker]


def _isins(session: Session, ticker: str) -> list[str]:
    return list(
        session.exec(
            select(InstrumentIdentifier.value).where(
                col(InstrumentIdentifier.instrument_id) == _iid(session, ticker),
                col(InstrumentIdentifier.scheme) == SCHEME_ISIN,
            )
        ).all()
    )


# --- parsing -----------------------------------------------------------------


def test_udiff_parses_with_exact_decimals_and_rupee_turnover() -> None:
    parsed = parse_cm(_text(UDIFF))
    assert parsed.format is FileFormat.CM_UDIFF
    assert parsed.trading_date == date(2025, 10, 20)
    assert len(parsed.rows) == 5
    rel = parsed.rows[0]
    assert (rel.symbol, rel.series, rel.isin) == ("RELIANCE", "EQ", "INE002A01018")
    assert rel.close == Decimal("1412.345678")
    assert rel.prev_close == Decimal("1400.05")
    assert (rel.volume, rel.trades) == (8123456, 201234)
    assert rel.turnover == Decimal("11473215678.91")
    assert {r.series for r in parsed.rows} == {"EQ", "GB", "SM"}


def test_legacy_parses_and_tolerates_the_trailing_empty_column() -> None:
    parsed = parse_cm(_text(LEGACY))
    assert parsed.format is FileFormat.CM_LEGACY
    assert parsed.trading_date == date(2024, 7, 5)
    assert [r.symbol for r in parsed.rows] == ["RELIANCE", "TCS", "NOTHELD"]
    assert parsed.rows[0].isin == "INE002A01018"
    assert parsed.rows[0].turnover == Decimal("14258765432.10")
    assert parsed.rows[2].series == "BE"


def test_sec_full_parses_padded_values_dashes_and_lakhs() -> None:
    parsed = parse_sec_full(_text(SEC))
    assert parsed.format is FileFormat.SEC_FULL
    assert parsed.trading_date == date(2025, 1, 1)
    rel, tcs, micro = parsed.rows
    assert (rel.deliverable_qty, rel.delivery_pct) == (3500000, Decimal("50.00"))
    assert tcs.delivery_pct == Decimal("68.04")
    assert (micro.series, micro.deliverable_qty, micro.delivery_pct) == ("BE", None, None)
    assert rel.turnover == Decimal("8540840000.00")  # 85408.40 lakhs in rupees


@pytest.mark.parametrize("path", [UDIFF, LEGACY, SEC])
def test_format_comes_from_the_header_in_any_order_and_case(path: Path) -> None:
    straight = parse_any(_text(path))
    shuffled = parse_any(_reshuffle(_text(path)))
    assert shuffled.format is straight.format
    assert shuffled.rows == straight.rows


def test_a_zip_with_one_csv_reads_as_that_csv(tmp_path: Path) -> None:
    path = _zip(tmp_path, UDIFF.name + ".zip", {UDIFF.name: _text(UDIFF)})
    assert parse_cm(read_bytes_as_text(path.read_bytes())).rows == parse_cm(_text(UDIFF)).rows


def test_a_zip_with_two_files_is_unrecognised(tmp_path: Path) -> None:
    path = _zip(tmp_path, "two.zip", {"a.csv": _text(UDIFF), "b.csv": _text(LEGACY)})
    with pytest.raises(UnrecognisedFile):
        read_bytes_as_text(path.read_bytes())


def test_an_unknown_header_is_unrecognised() -> None:
    with pytest.raises(UnrecognisedFile):
        parse_any("DATE,TICKER,PRICE\n2025-10-20,ABC,10\n")
    with pytest.raises(UnrecognisedFile):
        parse_sec_full(_text(UDIFF))


def test_a_bad_number_names_its_row() -> None:
    with pytest.raises(ParseError, match="row 3: ClsPric"):
        parse_any(_text(UDIFF).replace("3066.75,3067.00", "abc,3067.00", 1))


def test_dates_in_file_names() -> None:
    assert date_from_file_name("BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv.zip") == date(
        2025, 10, 20
    )
    assert date_from_file_name("cm05JUL2024bhav.csv.zip") == date(2024, 7, 5)
    assert date_from_file_name("sec_bhavdata_full_01012025.csv") == date(2025, 1, 1)
    assert date_from_file_name("prices.csv") is None


# --- the date check ----------------------------------------------------------


def test_date_check_against_the_name_the_calendar_and_the_rows() -> None:
    udiff = parse_cm(_text(UDIFF))
    assert check_date(udiff, date(2025, 10, 20)) is None
    assert check_date(udiff, None) is None
    assert "file name says 2025-10-17" in (check_date(udiff, date(2025, 10, 17)) or "")
    holiday = parse_cm(_redate_legacy("15-AUG-2024"))
    assert "not an NSE session" in (check_date(holiday, None) or "")
    mixed = parse_cm(_text(LEGACY).replace("05-JUL-2024", "04-JUL-2024", 1))
    assert "2 dates" in (check_date(mixed, None) or "")


def test_a_weekend_special_session_is_accepted() -> None:
    muhurat = parse_cm(_redate_legacy("12-NOV-2023"))  # Diwali Muhurat, a Sunday
    assert check_date(muhurat, date(2023, 11, 12)) is None


# --- the loader --------------------------------------------------------------


def test_load_matches_counts_and_keeps_raw_numbers(nse: Session) -> None:
    plan = plan_load(nse, parse_cm(_text(UDIFF)))
    # GB (gold bond) is not a loaded series; NOTHELD has no instrument.
    assert (plan.rows_total, plan.in_series, plan.matched, plan.unmatched) == (5, 4, 3, 1)
    assert plan.unmatched_symbols == ["NOTHELD"]
    assert "GB" not in LOAD_SERIES
    file_row = DataFile(
        source="nse_cm_udiff",
        file_name="x",
        sha256="0" * 64,
        size_bytes=1,
        archived_path="x",
        parse_status="parsed",
    )
    nse.add(file_row)
    nse.flush()
    assert file_row.id is not None
    result = apply_load(nse, plan, data_file_id=file_row.id, source="nse_cm_udiff")
    nse.commit()
    assert (result.inserted, result.updated, result.unchanged) == (3, 0, 0)
    rel = nse.get(EodRaw, (_iid(nse, "RELIANCE.NS"), date(2025, 10, 20), "EQ"))
    assert rel is not None
    assert rel.close == Decimal("1412.345678")
    assert rel.turnover == Decimal("11473215678.91")
    assert (rel.volume, rel.trades, rel.isin, rel.source) == (
        8123456,
        201234,
        "INE002A01018",
        "nse_cm_udiff",
    )
    sme = nse.get(EodRaw, (_iid(nse, "SMEDEMO.NS"), date(2025, 10, 20), "SM"))
    assert sme is not None

    again = apply_load(
        nse, plan_load(nse, parse_cm(_text(UDIFF))), data_file_id=file_row.id, source="nse_cm_udiff"
    )
    nse.commit()
    assert (again.inserted, again.updated, again.unchanged, again.isins_recorded) == (0, 0, 3, 0)
    assert len(nse.exec(select(EodRaw)).all()) == 3


def test_isin_is_recorded_once_and_then_matches(nse: Session, tmp_path: Path) -> None:
    root = tmp_path / "a"
    assert process_file(nse, UDIFF, apply=True, root=root).status == "parsed"
    assert _isins(nse, "RELIANCE.NS") == ["INE002A01018"]
    assert _isins(nse, "SMEDEMO.NS") == ["INE0DEMO1011"]
    report = process_file(nse, LEGACY, apply=True, root=root)
    assert report.status == "parsed"
    assert report.plan is not None and report.plan.isins_to_record == {}
    assert report.result is not None and report.result.isins_recorded == 0
    assert _isins(nse, "RELIANCE.NS") == ["INE002A01018"]
    assert (
        len(
            nse.exec(
                select(InstrumentIdentifier).where(col(InstrumentIdentifier.scheme) == SCHEME_ISIN)
            ).all()
        )
        == 3
    )


def test_a_different_current_isin_is_a_conflict_and_not_loaded(nse: Session) -> None:
    nse.add(
        InstrumentIdentifier(
            instrument_id=_iid(nse, "TCS.NS"),
            scheme=SCHEME_ISIN,
            value="INE999Z01011",
            valid_from=date(2020, 1, 1),
        )
    )
    nse.commit()
    plan = plan_load(nse, parse_cm(_text(UDIFF)))
    assert plan.isin_conflicts == 1
    assert _iid(nse, "TCS.NS") not in {iid for iid, _, _ in plan.rows}


def test_delivery_rows_load_into_extras(nse: Session, tmp_path: Path) -> None:
    report = process_file(nse, SEC, apply=True, root=tmp_path)
    assert report.status == "parsed"
    assert report.result is not None and report.result.inserted == 3
    micro = nse.get(EodExtras, (_iid(nse, "20MICRONS.NS"), date(2025, 1, 1), "BE"))
    assert micro is not None and (micro.deliverable_qty, micro.delivery_pct) == (None, None)
    rel = nse.get(EodExtras, (_iid(nse, "RELIANCE.NS"), date(2025, 1, 1), "EQ"))
    assert rel is not None and rel.delivery_pct == Decimal("50.00")
    assert nse.exec(select(EodRaw)).all() == []


def test_a_republished_file_updates_its_rows(nse: Session, tmp_path: Path) -> None:
    first = process_file(nse, LEGACY, apply=True, root=tmp_path)
    fixed = _write(tmp_path, LEGACY.name, _text(LEGACY).replace("3121.85", "3121.90"))
    second = process_file(nse, fixed, apply=True, root=tmp_path / "archive")
    assert second.result is not None
    assert (second.result.updated, second.result.unchanged) == (1, 1)
    rel = nse.get(EodRaw, (_iid(nse, "RELIANCE.NS"), date(2024, 7, 5), "EQ"))
    assert rel is not None and rel.close == Decimal("3121.90")
    assert rel.data_file_id == second.data_file_id != first.data_file_id


# --- files: archive, record, statuses ------------------------------------------


def test_zip_input_is_archived_as_received(nse: Session, tmp_path: Path) -> None:
    path = _zip(tmp_path, UDIFF.name + ".zip", {UDIFF.name: _text(UDIFF)})
    report = process_file(nse, path, apply=True, root=tmp_path / "archive")
    assert report.status == "parsed"
    stored = tmp_path / "archive" / "nse_cm_udiff" / "2025" / (UDIFF.name + ".zip")
    assert report.archived_path == str(stored)
    assert stored.read_bytes() == path.read_bytes()
    row = nse.exec(select(DataFile)).one()
    assert (row.file_name, row.size_bytes, row.rows_total, row.rows_loaded) == (
        UDIFF.name + ".zip",
        path.stat().st_size,
        5,
        3,
    )
    assert row.trading_date == date(2025, 10, 20)


def test_the_same_file_twice_is_recorded_once(nse: Session, tmp_path: Path) -> None:
    assert process_file(nse, LEGACY, apply=True, root=tmp_path).status == "parsed"
    again = process_file(nse, LEGACY, apply=True, root=tmp_path)
    assert again.status == ALREADY_RECORDED and again.ok
    assert len(nse.exec(select(DataFile)).all()) == 1


def test_a_date_mismatch_is_recorded_and_never_loaded(nse: Session, tmp_path: Path) -> None:
    renamed = _write(tmp_path, "BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv", _text(UDIFF))
    report = process_file(nse, renamed, apply=True, root=tmp_path / "archive")
    assert report.status == "date_mismatch" and not report.ok
    row = nse.exec(select(DataFile)).one()
    assert (row.parse_status, row.rows_loaded) == ("date_mismatch", 0)
    assert "file name says 2025-10-21" in (row.error or "")
    holiday = _write(tmp_path, "cm15AUG2024bhav.csv", _redate_legacy("15-AUG-2024"))
    assert process_file(nse, holiday, apply=True, root=tmp_path / "archive").status == (
        "date_mismatch"
    )
    assert nse.exec(select(EodRaw)).all() == []
    assert (
        nse.exec(
            select(InstrumentIdentifier).where(col(InstrumentIdentifier.scheme) == SCHEME_ISIN)
        ).all()
        == []
    )


def test_a_special_session_file_loads(nse: Session, tmp_path: Path) -> None:
    path = _write(tmp_path, "cm12NOV2023bhav.csv", _redate_legacy("12-NOV-2023"))
    report = process_file(nse, path, apply=True, root=tmp_path / "archive")
    assert report.status == "parsed"
    assert nse.get(EodRaw, (_iid(nse, "TCS.NS"), date(2023, 11, 12), "EQ")) is not None


def test_unrecognised_and_failed_files_are_recorded(nse: Session, tmp_path: Path) -> None:
    other = _write(tmp_path, "prices.csv", "DATE,TICKER,PRICE\n2025-10-20,ABC,10\n")
    bad = _write(tmp_path, "cm05JUL2024bhav.csv", _text(LEGACY).replace("4003.20", "n/a"))
    assert process_file(nse, other, apply=True, root=tmp_path / "a").status == "unrecognised"
    assert process_file(nse, bad, apply=True, root=tmp_path / "a").status == "failed"
    rows = {r.file_name: r for r in nse.exec(select(DataFile)).all()}
    assert rows["prices.csv"].source == "unknown"
    assert (tmp_path / "a" / "unknown" / "unknown" / "prices.csv").exists()
    assert "TOTTRDVAL" not in (rows["cm05JUL2024bhav.csv"].error or "")
    assert "CLOSE" in (rows["cm05JUL2024bhav.csv"].error or "")


# --- the CLI -----------------------------------------------------------------


def test_cli_dry_run_writes_nothing_and_apply_writes(
    engine, nse: Session, archive: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    assert cli.main(["nse-load", str(UDIFF), str(SEC)]) == 0
    out = capsys.readouterr().out
    assert "would load 3" in out and "dry run" in out
    assert nse.exec(select(DataFile)).all() == []
    assert nse.exec(select(EodRaw)).all() == []
    assert not archive.exists()

    assert cli.main(["nse-load", "--apply", str(UDIFF), str(SEC)]) == 0
    out = capsys.readouterr().out
    assert "loaded 3 (3 new" in out
    assert len(nse.exec(select(DataFile)).all()) == 2
    assert len(nse.exec(select(EodRaw)).all()) == 3
    assert (archive / "nse_sec_full" / "2025" / SEC.name).exists()

    assert cli.main(["nse-load", "--apply", str(UDIFF)]) == 0
    assert ALREADY_RECORDED in capsys.readouterr().out

    assert cli.main(["nse-files", "--limit", "5"]) == 0
    assert "2 file(s)" in capsys.readouterr().out


def test_cli_exits_1_on_a_mismatch_or_unknown_file(
    engine, nse: Session, archive: Path, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    renamed = _write(tmp_path, "BhavCopy_NSE_CM_0_0_0_20251017_F_0000.csv", _text(UDIFF))
    assert cli.main(["nse-load", str(LEGACY), str(renamed)]) == 1
    assert cli.main(["nse-load", str(tmp_path / "missing.csv")]) == 1
    assert nse.exec(select(DataFile)).all() == []
    assert "nse-load" not in cli.RECORDED_JOBS


# --- PostgreSQL ----------------------------------------------------------------


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_postgres_load_is_exact_and_idempotent(tmp_path: Path) -> None:
    with scratch_postgres_engine() as engine, Session(engine) as session:
        seed_symbols(session, *NSE_TICKERS, currency="INR")
        report = process_file(session, UDIFF, apply=True, root=tmp_path)
        assert report.result is not None and report.result.inserted == 3
        rel = session.get(EodRaw, (_iid(session, "RELIANCE.NS"), date(2025, 10, 20), "EQ"))
        assert rel is not None
        assert rel.close == Decimal("1412.345678")
        assert rel.turnover == Decimal("11473215678.9100")
        plan = plan_load(session, parse_cm(_text(UDIFF)))
        again = apply_load(session, plan, data_file_id=rel.data_file_id, source="nse_cm_udiff")
        session.commit()
        assert (again.inserted, again.updated, again.unchanged) == (0, 0, 3)
        assert len(_isins(session, "RELIANCE.NS")) == 1
