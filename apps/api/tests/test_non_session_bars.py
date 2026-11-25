"""Daily bars on closed days: report, then delete weekend ones on request (A0, MD-9)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import PriceBar
from stockviz.services.ingest.non_session_bars import delete_weekend_bars, find_non_session_bars
from tests.symbols import seed_symbols


def _bar(ticker: str, day: date, close: str, source: str = "bulk_1hr_resampled") -> PriceBar:
    price = Decimal(close)
    return PriceBar(
        ticker=ticker,
        ts=datetime(day.year, day.month, day.day),
        interval="1d",
        open=price,
        high=price,
        low=price,
        close=price,
        volume=100,
        source=source,
    )


@pytest.fixture
def bars(session: Session) -> Session:
    seed_symbols(session, "RELIANCE.NS", "INFY.NS", currency="INR")
    seed_symbols(session, "AAPL")
    session.add_all(
        [
            _bar("RELIANCE.NS", date(2026, 1, 23), "100"),  # Friday
            _bar("RELIANCE.NS", date(2026, 1, 24), "100"),  # Saturday, repeats Friday
            _bar("RELIANCE.NS", date(2026, 1, 25), "101"),  # Sunday, a new price
            _bar("RELIANCE.NS", date(2026, 1, 26), "101"),  # Monday, Republic Day
            _bar("RELIANCE.NS", date(2026, 1, 27), "102"),  # Tuesday
            _bar("RELIANCE.NS", date(2025, 2, 1), "90"),  # Budget-day Saturday session
            _bar("INFY.NS", date(2026, 1, 31), "50"),  # Saturday
            _bar("AAPL", date(2026, 1, 30), "200", source="yfinance"),  # Friday
        ]
    )
    session.commit()
    return session


def _dates(session: Session, ticker: str) -> list[date]:
    rows = session.exec(
        select(PriceBar.ts).where(PriceBar.ticker == ticker).order_by(col(PriceBar.ts))
    ).all()
    return [ts.date() for ts in rows]


def test_the_report_splits_weekends_from_holidays_and_marks_repeats(bars: Session) -> None:
    reports = {r.ticker: r for r in find_non_session_bars(bars)}
    assert set(reports) == {"RELIANCE.NS", "INFY.NS"}  # AAPL has none
    reliance = reports["RELIANCE.NS"]
    assert reliance.venue == "XNSE"
    assert reliance.weekend == [date(2026, 1, 24), date(2026, 1, 25)]
    assert reliance.holiday == [date(2026, 1, 26)]
    assert reliance.repeats == 2  # Saturday repeats Friday, Republic Day repeats Sunday
    assert reliance.sources == {"bulk_1hr_resampled": 3}


def test_a_special_saturday_session_is_not_listed(bars: Session) -> None:
    (reliance,) = find_non_session_bars(bars, ["RELIANCE.NS"])
    assert date(2025, 2, 1) not in reliance.weekend


def test_delete_removes_weekend_bars_of_the_named_tickers_only(bars: Session) -> None:
    deleted = delete_weekend_bars(bars, ["RELIANCE.NS"])
    bars.commit()
    assert deleted == {"RELIANCE.NS": 2}
    assert _dates(bars, "RELIANCE.NS") == [
        date(2025, 2, 1),
        date(2026, 1, 23),
        date(2026, 1, 26),  # holiday bars are reported, never deleted here
        date(2026, 1, 27),
    ]
    assert _dates(bars, "INFY.NS") == [date(2026, 1, 31)]


def test_delete_needs_tickers(bars: Session) -> None:
    with pytest.raises(ValueError, match="name the tickers"):
        delete_weekend_bars(bars, [])


def test_the_command_reports_without_deleting(
    bars: Session, engine, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    assert cli.main(["non-session-bars"]) == 0
    out = capsys.readouterr().out
    assert "RELIANCE.NS (XNSE): weekend 2, holiday 1, repeat the previous bar 2" in out
    assert "2 ticker(s): 3 weekend bar(s), 1 holiday bar(s)" in out
    assert "dry run: nothing deleted" in out
    assert len(_dates(bars, "RELIANCE.NS")) == 6


def test_the_command_deletes_only_with_tickers(
    bars: Session, engine, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    assert cli.main(["non-session-bars", "--apply"]) == 2
    assert len(_dates(bars, "RELIANCE.NS")) == 6
    assert cli.main(["non-session-bars", "--apply", "infy.ns"]) == 0
    assert "deleted INFY.NS: 1" in capsys.readouterr().out
    bars.expire_all()
    assert _dates(bars, "INFY.NS") == []
    assert len(_dates(bars, "RELIANCE.NS")) == 6
