"""Exchange calendars decide which sessions are complete (Phase 4, batch 4.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stockviz.models import PriceBar
from stockviz.services.ingest.bar_semantics import completed_daily_bars, latest_completed_session
from stockviz.services.markets.calendar import (
    is_session,
    session_on_or_before,
    venue_for_ticker,
)

THANKSGIVING_CRON = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)  # US closed, London open


@pytest.mark.parametrize(
    ("ticker", "venue"),
    [
        ("AAPL", "XNYS"),
        ("RELIANCE.NS", "XBOM"),
        ("BARC.L", "XLON"),
        ("SAP.DE", "XETR"),
        ("SHOP.TO", "XTSE"),
        ("7203.T", "XTKS"),
    ],
)
def test_venue_comes_from_the_ticker_suffix(ticker: str, venue: str) -> None:
    assert venue_for_ticker(ticker) == venue


def test_a_us_holiday_expects_the_session_before() -> None:
    assert not is_session(date(2026, 11, 26))
    assert latest_completed_session(THANKSGIVING_CRON) == date(2026, 11, 25)


def test_other_markets_keep_their_own_session_on_a_us_holiday() -> None:
    assert latest_completed_session(THANKSGIVING_CRON, "XLON") == date(2026, 11, 26)


def test_an_early_close_completes_early() -> None:
    # 27 Nov 2026: New York closes at 13:00 (18:00 UTC); complete at 18:45 UTC.
    assert latest_completed_session(datetime(2026, 11, 27, 18, 30, tzinfo=UTC)) == date(
        2026, 11, 25
    )
    assert latest_completed_session(datetime(2026, 11, 27, 18, 50, tzinfo=UTC)) == date(
        2026, 11, 27
    )


def test_tokyo_tomorrow_has_not_traded_at_the_new_york_cron() -> None:
    # 22:00 UTC is 07:00 the next morning in Tokyo, before its open.
    cron = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
    assert latest_completed_session(cron, "XTKS") == date(2026, 11, 11)


def test_an_expiry_on_a_holiday_settles_on_the_session_before() -> None:
    assert session_on_or_before(date(2026, 4, 3)) == date(2026, 4, 2)  # Good Friday
    assert session_on_or_before(date(2026, 11, 28)) == date(2026, 11, 27)  # Saturday


def test_outside_a_calendar_the_weekday_rule_applies() -> None:
    # XBOM in this package version ends on 31 Dec 2026.
    assert is_session(date(2027, 3, 1), "XBOM")
    assert not is_session(date(2027, 3, 6), "XBOM")
    assert latest_completed_session(datetime(2027, 3, 2, 22, 0, tzinfo=UTC), "XBOM") == date(
        2027, 3, 2
    )


def test_bars_are_judged_by_their_own_venue() -> None:
    one = Decimal(1)
    bar = PriceBar(
        ticker="BARC.L",
        ts=datetime(2026, 11, 26),
        interval="1d",
        open=one,
        high=one,
        low=one,
        close=one,
        volume=1,
    )
    assert completed_daily_bars([bar], now=THANKSGIVING_CRON, venue="XLON") == [bar]
    assert completed_daily_bars([bar], now=THANKSGIVING_CRON) == []
