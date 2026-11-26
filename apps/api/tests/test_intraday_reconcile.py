"""Reconciliation of intraday bars (A6.1): the resample maths, tolerances, the CLI.

Synthetic bars only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session

from stockviz import cli
from stockviz.models import PriceBar
from stockviz.services.intraday.files import KINDS
from stockviz.services.intraday.load import load_files
from stockviz.services.intraday.reconcile import (
    DailyAgg,
    compare,
    pct_diff,
    reconcile,
    reconcile_moneycontrol,
    resample_daily,
)
from tests.symbols import seed_symbols

D = Decimal


def test_resample_daily_takes_first_open_extremes_last_close_and_summed_volume() -> None:
    # Two IST sessions; given out of order. 03:45 UTC = 09:15 IST.
    bars = [
        (datetime(2025, 11, 25, 3, 46), D("101"), D("105"), D("100"), D("104"), 20),
        (datetime(2025, 11, 25, 3, 45), D("100"), D("102"), D("99"), D("101"), 10),
        (datetime(2025, 11, 25, 9, 59), D("104"), D("104.5"), D("98"), D("103"), 5),
        (datetime(2025, 11, 26, 3, 45), D("200"), D("201"), D("199"), D("200"), 1),
    ]
    daily = resample_daily(bars, "XNSE")
    assert daily[date(2025, 11, 25)] == DailyAgg(D("100"), D("105"), D("98"), D("103"), 35, 3)
    assert daily[date(2025, 11, 26)].bars == 1


def test_us_bars_are_grouped_by_new_york_date() -> None:
    # 20:59 New York on 25 Nov is 01:59 UTC on 26 Nov: still the 25th's session date.
    bars = [(datetime(2025, 11, 26, 1, 59), D("1"), D("1"), D("1"), D("1"), 1)]
    assert list(resample_daily(bars, "XNYS")) == [date(2025, 11, 25)]


def test_compare_counts_mismatches_by_field_and_volume() -> None:
    ref = {
        date(2025, 1, d): DailyAgg(D("100"), D("110"), D("90"), D("105"), 1000) for d in (1, 2, 3)
    }
    mine = {
        date(2025, 1, 1): DailyAgg(D("100.4"), D("110"), D("90"), D("105"), 1050),  # within
        date(2025, 1, 2): DailyAgg(D("101"), D("110"), D("90"), D("105"), 1000),  # open 1%
        date(2025, 1, 3): DailyAgg(D("100"), D("110"), D("90"), D("105"), 1200),  # volume 20%
        date(2025, 1, 4): DailyAgg(D("100"), D("110"), D("90"), D("105"), 1000),  # no reference
    }
    r = compare("X", mine, ref)
    assert (r.compared, r.matched, r.only_intraday, r.only_reference) == (3, 1, 1, 0)
    assert r.field_mismatches["open"] == 1 and r.volume_mismatches == 1
    assert round(r.worst["open"], 6) == 1.0
    assert round(r.worst["volume"], 6) == 20.0
    assert r.median_volume_ratio == 1.05
    assert [m.field for m in r.mismatches] == ["volume", "open"]  # worst first
    assert not r.matches
    index = compare("IDX", mine, ref, check_volume=False)
    assert index.matched == 2 and index.volume_mismatches == 0


def test_pct_diff() -> None:
    assert pct_diff(D("101"), D("100")) == 1.0
    assert pct_diff(D("0"), D("0")) == 0.0


def _minute_file(path: Path, day: str, closes: list[str], *, offset: str = "+05:30") -> Path:
    base = datetime.fromisoformat(f"{day} 09:15")
    lines = ["date,open,high,low,close,volume"]
    for i, c in enumerate(closes):
        stamp = (base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{stamp}{offset},{c},{D(c) + 1},{D(c) - 1},{c},10")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_reconcile_against_stored_daily_bars_and_the_cli(
    session: Session, tmp_path: Path, monkeypatch, capsys
) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    f = _minute_file(tmp_path / "TCS_bulk_data.csv", "2025-11-25", ["100", "102", "101"])
    load_files(session, [(f, "TCS.NS")], KINDS["bulk1m"], apply=True)
    session.add(
        PriceBar(
            ticker="TCS.NS",
            ts=datetime(2025, 11, 25),
            interval="1d",
            open=D("100"),
            high=D("103"),
            low=D("99"),
            close=D("101"),
            volume=30,
            source="yfinance",
        )
    )
    session.commit()
    [r] = reconcile(session)
    assert (r.ticker, r.compared, r.matched) == ("TCS.NS", 1, 1)
    assert r.matches

    monkeypatch.setattr(cli, "engine", session.get_bind())
    assert cli.main(["intraday-reconcile"]) == 0
    out = capsys.readouterr().out
    assert "TCS.NS: compared 1, matched 1 (100.0%)" in out
    assert "1 match on at least 99%" in out


def test_reconcile_minutes_against_hourly(session: Session, tmp_path: Path) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    m = _minute_file(tmp_path / "TCS_bulk_data.csv", "2025-11-25", ["100", "102", "101"])
    h = _minute_file(tmp_path / "TCS_1hr_bulk_data.csv", "2025-11-25", ["100"])
    load_files(session, [(m, "TCS.NS")], KINDS["bulk1m"], apply=True)
    load_files(session, [(h, "TCS.NS")], KINDS["bulk1h"], apply=True)
    [r] = reconcile(session, against="60m")
    # The hour's bar: open 100, high 101, low 99, close 100 vs minutes' 100/103/99/101.
    assert r.compared == 1 and r.matched == 0
    assert r.field_mismatches["high"] == 1 and r.field_mismatches["close"] == 1


def test_moneycontrol_naive_ist_matches_the_bulk_instants(session: Session, tmp_path: Path) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    bulk = _minute_file(tmp_path / "TCS_bulk_data.csv", "2025-11-25", ["100", "102", "101"])
    load_files(session, [(bulk, "TCS.NS")], KINDS["bulk1m"], apply=True)
    mc = _minute_file(
        tmp_path / "2025_TCS_1m_MoneyControl.csv", "2025-11-25", ["100", "102", "103"], offset=""
    )
    # An after-hours row, as MoneyControl files hold.
    with mc.open("a", encoding="utf-8") as fh:
        fh.write("2025-11-25 15:45:00,101,102,100,101,7\n")
    r = reconcile_moneycontrol(session, mc, "TCS.NS")
    assert r.status == "compared"
    assert (r.in_session, r.off_session, r.off_session_with_volume) == (3, 1, 1)
    assert (r.matched_instants, r.only_file, r.only_stored) == (3, 0, 0)
    assert r.close_mismatches == 1  # 103 against 101
    assert r.daily is not None and r.daily.compared == 1
