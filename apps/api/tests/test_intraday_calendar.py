"""Session minutes (A6.1): each session's open and close in UTC, special hours included."""

from __future__ import annotations

from datetime import UTC, date, datetime

from stockviz.services.markets import india_holidays
from stockviz.services.markets.calendar import session_complete_at, session_minutes


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def test_normal_nse_day_is_0915_to_1530_ist() -> None:
    hours = session_minutes(date(2025, 11, 25), "XNSE")
    assert hours is not None
    assert (hours.open, hours.close) == (_utc(2025, 11, 25, 3, 45), _utc(2025, 11, 25, 10, 0))
    assert hours.minutes == 375
    assert hours.special is None
    assert hours.contains(_utc(2025, 11, 25, 9, 59))  # the 15:29 IST minute
    assert not hours.contains(_utc(2025, 11, 25, 10, 0))  # 15:30 IST is the close


def test_muhurat_2023_has_its_evening_hours() -> None:
    hours = session_minutes(date(2023, 11, 12), "XNSE")
    assert hours is not None
    # 18:15-19:15 IST, a Sunday.
    assert (hours.open, hours.close) == (_utc(2023, 11, 12, 12, 45), _utc(2023, 11, 12, 13, 45))
    assert hours.minutes == 60
    assert "Muhurat" in (hours.special or "")
    assert not hours.contains(_utc(2023, 11, 12, 3, 45))  # no morning session that day
    # The daily bar is complete 45 minutes after the special close, not 15:30's.
    assert session_complete_at(date(2023, 11, 12), "XNSE") == _utc(2023, 11, 12, 14, 30)


def test_weekday_muhurat_on_bse_too() -> None:
    hours = session_minutes(date(2025, 10, 21), "XBOM")
    assert hours is not None
    assert (hours.open, hours.close) == (_utc(2025, 10, 21, 8, 15), _utc(2025, 10, 21, 9, 15))


def test_budget_saturday_trades_regular_hours() -> None:
    hours = session_minutes(date(2025, 2, 1), "XNSE")
    assert hours is not None
    assert (hours.open, hours.close) == (_utc(2025, 2, 1, 3, 45), _utc(2025, 2, 1, 10, 0))
    assert "Budget" in (hours.special or "")
    assert session_minutes(date(2025, 2, 8), "XNSE") is None  # an ordinary Saturday


def test_dr_switch_session_pauses_between_spans() -> None:
    hours = session_minutes(date(2024, 3, 2), "XNSE")
    assert hours is not None
    assert len(hours.spans) == 2
    assert hours.minutes == 45 + 60
    assert hours.contains(_utc(2024, 3, 2, 4, 29))  # 09:59 IST
    assert not hours.contains(_utc(2024, 3, 2, 5, 0))  # 10:30 IST: paused
    assert hours.contains(_utc(2024, 3, 2, 6, 0))  # 11:30 IST
    # A 60-minute bar opening at 10:15 IST touches no trading minute.
    assert not hours.overlaps(_utc(2024, 3, 2, 4, 45), _utc(2024, 3, 2, 5, 45))


def test_xnys_half_day_closes_at_1300_new_york() -> None:
    hours = session_minutes(date(2026, 11, 27), "XNYS")
    assert hours is not None
    assert (hours.open, hours.close) == (_utc(2026, 11, 27, 14, 30), _utc(2026, 11, 27, 18, 0))
    assert hours.minutes == 210
    assert session_minutes(date(2026, 11, 26), "XNYS") is None  # Thanksgiving


def test_holidays_and_unknown_venues_have_no_session() -> None:
    assert session_minutes(date(2026, 1, 26), "XNSE") is None  # Republic Day
    assert session_minutes(date(2026, 11, 25), "XXXX") is None


def test_every_special_hours_day_is_a_session_with_sane_spans() -> None:
    for day, spans in india_holidays.SPECIAL_HOURS.items():
        hours = session_minutes(day, "XNSE")
        assert hours is not None, day
        assert len(hours.spans) == len(spans)
        for start, end in hours.spans:
            assert start < end
        assert all(a[1] <= b[0] for a, b in zip(hours.spans, hours.spans[1:], strict=False))
