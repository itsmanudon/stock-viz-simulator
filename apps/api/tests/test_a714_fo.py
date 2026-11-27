"""A7.14 (M6.1, M6.3): the owner's option minute files as daily summaries.

Every file here is synthetic, written by the test in the files' real header
and quoting; never the owner's rows.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import FoDaily, FoFile
from stockviz.services.fo import load as fo_load
from stockviz.services.fo.summary import summarise

HEADER = "date,time,symbol,option_type,type,strike_offset,open,high,low,close,volume,oi,iv,spot\n"


def _line(
    day: str,
    time: str,
    kind: str,
    offset: str,
    close: float,
    vol: int,
    oi: int,
    iv: float,
    spot: float,
) -> str:
    name = "CALL" if kind == "CE" else "PUT"
    return f'"=""{day}""",{time},NIFTY,{name},{kind},{offset},{close},{close},{close},{close},{vol},{oi},{iv},{spot}\n'


def _write(folder: Path, name: str, lines: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(HEADER + "".join(lines), encoding="utf-8")
    return path


def _day(day: str, iv: float, *, spot: float = 24000.0) -> list[str]:
    out = []
    for offset, k in (("ATM", 0), ("ATM+2", 2), ("ATM-2", -2)):
        for kind in ("CE", "PE"):
            skew = 2.0 if (kind == "PE" and k < 0) else 0.0
            out.append(
                _line(day, "09:15:00", kind, offset, 100, 10, 1000, iv + 5 + skew, spot - 50)
            )
            out.append(
                _line(
                    day,
                    "15:29:00",
                    kind,
                    offset,
                    120,
                    20,
                    2000 if kind == "PE" else 1000,
                    iv + skew,
                    spot,
                )
            )
    return out


def test_parsing_helpers() -> None:
    assert fo_load.parse_day('="10-06-24"') == date(2024, 6, 10)
    assert fo_load.parse_offset("ATM") == 0 and fo_load.parse_offset("ATM+3") == 3
    assert fo_load.parse_offset("ATM-2") == -2
    with pytest.raises(ValueError):
        fo_load.parse_offset("OTM")


def test_dry_run_then_apply_keeps_the_last_minute_and_sums_volume(
    session: Session, tmp_path: Path
) -> None:
    root = tmp_path / "NIFTY"
    # One day split across two part files, plus an off-session minute and a bad row.
    lines = _day("23-07-24", 14.0)
    _write(root / "weekly", "NIFTY_part_1.csv", lines[:6])
    _write(
        root / "weekly",
        "NIFTY_part_2.csv",
        [*lines[6:], _line("23-07-24", "16:00:00", "CE", "ATM", 1, 1, 1, 99, 1), "bad,row\n"],
    )
    (root / "BANKNIFTY_active_futures.csv").write_text(
        "date,time,symbol,expiry_date,close\n", encoding="utf-8"
    )
    dry = fo_load.load_dir(session, root)
    assert [f.skipped is not None for f in dry.files] == [True, False, False]
    assert dry.summaries == 6 and not dry.applied
    assert session.exec(select(FoDaily)).all() == []
    assert sum(f.rejected for f in dry.files) == 1 and sum(f.off_session for f in dry.files) == 1

    done = fo_load.load_dir(session, root, apply=True)
    assert done.applied and done.days[("NIFTY", "weekly")] == (date(2024, 7, 23), date(2024, 7, 23))
    atm = session.get(FoDaily, ("NIFTY", "weekly", date(2024, 7, 23), "CE", 0))
    assert atm is not None and atm.iv == 14.0 and atm.volume == 30 and atm.minutes == 2
    assert atm.last_minute == "15:29:00" and float(atm.spot) == 24000.0
    again = fo_load.load_dir(session, root, apply=True)
    assert all(f.known for f in again.files if f.skipped is None)
    assert len(session.exec(select(FoDaily)).all()) == 6
    assert len(session.exec(select(FoFile)).all()) == 2  # the futures file is not recorded


def test_series_comes_from_the_folder(tmp_path: Path) -> None:
    assert fo_load.series_for(tmp_path / "weekly" / "a.csv") == "weekly"
    assert fo_load.series_for(tmp_path / "Options_minute" / "a.csv") == "nearest"


def test_loader_refuses_a_remote_database(session: Session, tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "weekly", "a.csv", _day("23-07-24", 14.0))
    monkeypatch.setattr(fo_load, "local_database_problem", lambda url: "the host is remote")
    with pytest.raises(fo_load.FoLoadRefused, match="local database only"):
        fo_load.load_dir(session, tmp_path)


def test_summary_iv_rank_skew_and_pcr(session: Session, tmp_path: Path) -> None:
    lines: list[str] = []
    ivs = [10 + (i % 10) for i in range(70)]
    for i, iv in enumerate(ivs):
        d = date(2024, 8, 1).toordinal() + i
        day = date.fromordinal(d)
        lines += _day(day.strftime("%d-%m-%y"), float(iv))
    _write(tmp_path / "weekly", "all.csv", lines)
    fo_load.load_dir(session, tmp_path, apply=True)
    (s,) = summarise(list(session.exec(select(FoDaily)).all()))
    assert s.underlying == "NIFTY" and len(s.days) == 70
    last = s.days[-1]
    assert last.atm_iv == pytest.approx(ivs[-1])  # ATM call and put share the day's IV
    assert last.skew == pytest.approx(2.0)  # ATM-2 put IV minus ATM+2 call IV
    assert last.pcr == pytest.approx(2.0)  # put OI 2000 x3 over call OI 1000 x3
    assert s.iv_rank == pytest.approx(100.0)  # 19 is the window's high
    assert s.iv_percentile is not None and 80 < s.iv_percentile < 100
    assert [o for o, _c, _p in s.smile] == [-2, 0, 2]


def test_route(client: TestClient, session: Session, tmp_path: Path) -> None:
    assert client.get("/v1/fo/india").json()["underlyings"] == []
    _write(tmp_path / "weekly", "a.csv", _day("23-07-24", 14.0))
    fo_load.load_dir(session, tmp_path, apply=True)
    out = client.get("/v1/fo/india").json()
    (u,) = out["underlyings"]
    assert u["underlying"] == "NIFTY" and u["sessions"] == 1 and u["iv_rank"] is None
    assert "local database only" in out["source_note"]


def test_railway_never_runs_the_fo_loader() -> None:
    railway = Path(__file__).resolve().parents[3] / ".railway" / "railway.ts"
    assert railway.exists()
    assert "fo-load" not in railway.read_text(encoding="utf-8")
