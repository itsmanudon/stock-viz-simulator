"""NSE and BSE calendars from the maintained holiday table (A0, "Calendar first")."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest

from stockviz.services.event_study import BENCHMARK_BY_VENUE
from stockviz.services.markets import calendar as cal
from stockviz.services.markets import india_holidays
from stockviz.services.markets.calendar import (
    holiday_basis,
    indian_holidays,
    is_session,
    latest_completed_session,
    previous_session,
    session_complete_at,
    session_on_or_before,
    venue_for_ticker,
)
from stockviz.services.risk.scenarios import proxy_for

INDIAN = ("XNSE", "XBOM")


def _sessions(venue: str) -> Any:
    calendar = cal._calendar(venue)
    assert calendar is not None
    return calendar.sessions


@pytest.mark.parametrize("venue", INDIAN)
def test_january_2027_resolves_past_the_old_end_of_the_calendar(venue: str) -> None:
    # The package's BSE calendar stopped on 31 Dec 2026; these used the weekday rule.
    assert is_session(date(2027, 1, 1), venue)  # Friday: NSE trades on New Year's Day
    assert not is_session(date(2027, 1, 2), venue)  # Saturday
    assert is_session(date(2027, 1, 25), venue)
    assert not is_session(date(2027, 1, 26), venue)  # Tuesday, Republic Day
    assert is_session(date(2027, 1, 27), venue)
    assert holiday_basis(date(2027, 1, 26), venue) == "provisional"


@pytest.mark.parametrize("venue", INDIAN)
def test_republic_day_2027_moves_the_completed_session_back(venue: str) -> None:
    evening = datetime(2027, 1, 26, 22, 0, tzinfo=UTC)
    assert latest_completed_session(evening, venue) == date(2027, 1, 25)
    assert previous_session(date(2027, 1, 27), venue) == date(2027, 1, 25)
    assert session_on_or_before(date(2027, 1, 26), venue) == date(2027, 1, 25)


def test_an_indian_session_completes_45_minutes_after_the_close() -> None:
    # 15:30 IST is 10:00 UTC.
    assert session_complete_at(date(2027, 1, 27), "XNSE") == datetime(
        2027, 1, 27, 10, 45, tzinfo=UTC
    )
    assert latest_completed_session(datetime(2027, 1, 27, 10, 40, tzinfo=UTC), "XNSE") == date(
        2027, 1, 25
    )
    assert latest_completed_session(datetime(2027, 1, 27, 10, 50, tzinfo=UTC), "XNSE") == date(
        2027, 1, 27
    )


def test_nse_listings_and_nifty_use_the_nse_calendar() -> None:
    assert venue_for_ticker("RELIANCE.NS") == "XNSE"
    assert venue_for_ticker("^NSEI") == "XNSE"
    assert venue_for_ticker("RELIANCE.BO") == "XBOM"
    assert proxy_for("RELIANCE.NS") == "^NSEI"
    assert proxy_for("RELIANCE.BO") == "^NSEI"
    assert proxy_for("AAPL") == "^GSPC"
    assert BENCHMARK_BY_VENUE["XNSE"] == "^NSEI"


def test_nse_and_bse_close_on_the_same_days() -> None:
    assert _sessions("XNSE").equals(_sessions("XBOM"))


@pytest.mark.parametrize("venue", INDIAN)
def test_history_before_2027_matches_the_package_bse_calendar(venue: str) -> None:
    import exchange_calendars as xcals

    package = xcals.get_calendar("XBOM")
    ours = _sessions(venue)
    ours = ours[(ours >= package.first_session) & (ours <= package.last_session)]
    assert ours.equals(package.sessions)


def test_the_maintained_2026_list_matches_the_package() -> None:
    from exchange_calendars.exchange_calendar_xbom import precomputed_bse_holidays

    package_2026 = {
        stamp.date()
        for stamp in precomputed_bse_holidays
        if stamp.year == 2026 and stamp.weekday() < 5
    }
    assert set(india_holidays.OFFICIAL_HOLIDAYS[2026]) == package_2026
    assert all(day.weekday() < 5 for day in india_holidays.OFFICIAL_HOLIDAYS[2026])


def test_a_provisional_year_closes_only_fixed_date_weekday_holidays() -> None:
    assert india_holidays.year_status(2026) == "official"
    assert india_holidays.year_status(2027) == "provisional"
    assert india_holidays.year_status(india_holidays.PROVISIONAL_THROUGH + 1) == "none"
    # 1 May, 2 Oct and 25 Dec 2027 are Saturdays, 15 Aug a Sunday: not listed.
    assert india_holidays.holidays_for_year(2027) == {
        date(2027, 1, 26): "Republic Day",
        date(2027, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    }
    for day in india_holidays.holidays_for_year(2027):
        assert day.weekday() < 5
        assert not is_session(day, "XNSE")


def test_every_listed_holiday_is_closed_and_every_other_weekday_open() -> None:
    closed = set(indian_holidays())
    sessions = {stamp.date() for stamp in _sessions("XNSE")}
    day = date(2026, 1, 1)
    while day <= date(india_holidays.PROVISIONAL_THROUGH, 12, 31):
        if day.weekday() < 5:
            assert (day in sessions) == (day not in closed), day
        day = date.fromordinal(day.toordinal() + 1)


def test_after_the_table_the_weekday_rule_applies() -> None:
    after = date(india_holidays.PROVISIONAL_THROUGH + 1, 1, 27)  # a Monday in 2031
    assert holiday_basis(after, "XNSE") == "weekdays"
    assert is_session(after, "XNSE")
    assert holiday_basis(date(2026, 3, 3), "XNSE") == "official"
    assert holiday_basis(date(2020, 3, 3), "XNSE") == "calendar"
    assert holiday_basis(date(2027, 3, 1), "XNYS") == "calendar"


def test_a_provisional_year_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    cal._warned.discard("XNSE:2028:provisional")
    with caplog.at_level(logging.WARNING, logger=cal.__name__):
        is_session(date(2028, 2, 1), "XNSE")
        is_session(date(2028, 2, 2), "XNSE")
    warnings = [r for r in caplog.records if "2028 are provisional" in r.getMessage()]
    assert len(warnings) == 1
