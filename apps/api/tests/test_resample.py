"""A1.4a: weekly and monthly bars resampled on read from daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from stockviz.services.bars.resample import (
    is_partial,
    last_session_in_period,
    period_end,
    period_start,
    resample,
)

LATER = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str | None = "yfinance"
    adjustment_semantics: str = "split_adjusted"


def bar(day: date, o: str, h: str, low: str, c: str, v: int = 100, **kw) -> Bar:
    return Bar(
        datetime.combine(day, datetime.min.time()),
        Decimal(o),
        Decimal(h),
        Decimal(low),
        Decimal(c),
        v,
        **kw,
    )


def test_periods() -> None:
    assert period_start(date(2025, 11, 23), "1wk") == date(2025, 11, 17)  # Sunday -> Monday
    assert period_end(date(2025, 11, 17), "1wk") == date(2025, 11, 23)
    assert period_start(date(2024, 2, 29), "1mo") == date(2024, 2, 1)
    assert period_end(date(2024, 2, 3), "1mo") == date(2024, 2, 29)
    assert period_end(date(2025, 12, 31), "1mo") == date(2025, 12, 31)
    with pytest.raises(ValueError):
        period_start(date(2025, 1, 1), "1h")


def test_a_week_with_an_nse_holiday() -> None:
    # 26 Feb 2025 (Mahashivratri) was an NSE holiday: four sessions that week.
    days = [date(2025, 2, 24), date(2025, 2, 25), date(2025, 2, 27), date(2025, 2, 28)]
    bars = [
        bar(days[0], "100", "105", "99", "104", 10),
        bar(days[1], "104", "110", "103", "108", 20),
        bar(days[2], "108", "109", "95", "96", 30),
        bar(days[3], "96", "101", "94", "100", 40),
    ]
    (week,) = resample(bars, "1wk", venue="XNSE", now=LATER)
    assert week.ts == datetime(2025, 2, 28)
    assert (week.open, week.high, week.low, week.close) == (
        Decimal("100"),
        Decimal("110"),
        Decimal("94"),
        Decimal("100"),
    )
    assert week.volume == 100 and week.sessions == 4
    # The holiday is not a missing session: the week is over and closed.
    assert week.partial is False
    assert last_session_in_period(date(2025, 2, 24), "1wk", "XNSE") == date(2025, 2, 28)


def test_a_month_boundary_splits_the_bars() -> None:
    days = [date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31), date(2025, 2, 3)]
    bars = [bar(d, "10", "12", "9", str(11 + i)) for i, d in enumerate(days)]
    jan, feb = resample(bars, "1mo", venue="XNYS", now=datetime(2025, 2, 4, 12, tzinfo=UTC))
    assert (jan.ts, jan.sessions, jan.close, jan.partial) == (
        datetime(2025, 1, 31),
        3,
        Decimal("13"),
        False,
    )
    # February is still running: a partial bar, its timestamp the last stored session.
    assert (feb.ts, feb.sessions, feb.partial) == (datetime(2025, 2, 3), 1, True)
    # The same bars as weeks: Mon 27 Jan-Fri 31 Jan, then the week of 3 Feb.
    w1, w2 = resample(bars, "1wk", venue="XNYS", now=datetime(2025, 2, 4, 12, tzinfo=UTC))
    assert (w1.sessions, w1.partial, w2.sessions, w2.partial) == (3, False, 1, True)


def test_the_current_week_is_partial_until_its_last_session_is_complete() -> None:
    week = [date(2025, 11, 17) + timedelta(days=i) for i in range(5)]  # Mon-Fri
    bars = [bar(d, "10", "11", "9", "10") for d in week]
    # Wednesday night: Thursday and Friday are still to come.
    wed = resample(bars[:3], "1wk", venue="XNYS", now=datetime(2025, 11, 19, 23, tzinfo=UTC))
    assert wed[-1].partial is True
    # Friday's bar is stored but its session completes at 21:45 UTC.
    fri_early = datetime(2025, 11, 21, 20, tzinfo=UTC)
    assert resample(bars, "1wk", venue="XNYS", now=fri_early)[-1].partial is True
    fri_late = datetime(2025, 11, 21, 22, tzinfo=UTC)
    assert resample(bars, "1wk", venue="XNYS", now=fri_late)[-1].partial is False


def test_only_the_newest_bar_can_be_partial() -> None:
    # A gap in old data (Thursday and Friday missing) is not "so far": a later
    # week exists, so the old week is over.
    bars = [
        bar(date(2025, 11, 10), "10", "11", "9", "10"),
        bar(date(2025, 11, 11), "10", "11", "9", "10"),
        bar(date(2025, 11, 17), "10", "11", "9", "10"),
    ]
    old, new = resample(bars, "1wk", venue="XNYS", now=LATER)
    assert old.partial is False and old.sessions == 2
    # The newest week lacks Tue-Fri, so it is flagged even long after.
    assert new.partial is True
    assert is_partial(date(2025, 11, 21), "1wk", "XNYS", LATER) is False
    with pytest.raises(ValueError):
        is_partial(date(2025, 11, 21), "1wk", "XNYS", datetime(2030, 1, 1))


def test_a_split_adjusted_series_keeps_its_ratios() -> None:
    days = [date(2025, 3, 3) + timedelta(days=i) for i in range(10)]
    days = [d for d in days if d.weekday() < 5]
    raw = [
        bar(d, str(200 + i), str(210 + i), str(190 + i), str(205 + i), 1000)
        for i, d in enumerate(days)
    ]
    # The same history after a 2-for-1 split: prices halved, volume doubled.
    halved = [Bar(b.ts, b.open / 2, b.high / 2, b.low / 2, b.close / 2, b.volume * 2) for b in raw]
    a = resample(raw, "1wk", venue="XNYS", now=LATER)
    b = resample(halved, "1wk", venue="XNYS", now=LATER)
    assert len(a) == len(b) == 2
    for x, y in zip(a, b, strict=True):
        assert (y.open, y.high, y.low, y.close) == (x.open / 2, x.high / 2, x.low / 2, x.close / 2)
        assert y.volume == x.volume * 2
    assert b[1].close / b[0].close == a[1].close / a[0].close
    assert isinstance(b[0].close, Decimal)


def test_a_venue_in_another_time_zone() -> None:
    # Tokyo's Friday session completes at 07:15 UTC, New York's at 21:45 UTC.
    week = [date(2025, 11, 17) + timedelta(days=i) for i in range(5)]
    bars = [bar(d, "10", "11", "9", "10") for d in week]
    before = datetime(2025, 11, 21, 6, tzinfo=UTC)
    after = datetime(2025, 11, 21, 8, tzinfo=UTC)
    assert resample(bars, "1wk", venue="XTKS", now=before)[-1].partial is True
    assert resample(bars, "1wk", venue="XTKS", now=after)[-1].partial is False
    assert resample(bars, "1wk", venue="XNYS", now=after)[-1].partial is True
    # An aware timestamp is dated in the venue's zone: 15:00 UTC on Sunday is
    # Monday in Tokyo, so it opens the next week.
    one = Decimal(1)
    sunday_utc = Bar(datetime(2025, 11, 23, 15, tzinfo=UTC), one, one, one, one, 1)
    weeks = resample([*bars, sunday_utc], "1wk", venue="XTKS", now=LATER)
    assert [w.sessions for w in weeks] == [5, 1]


def test_mixed_sources_and_bases_say_so() -> None:
    bars = [
        bar(date(2025, 11, 17), "10", "11", "9", "10", source="yfinance"),
        bar(date(2025, 11, 18), "10", "11", "9", "10", source="alpha_vantage"),
        bar(date(2025, 11, 24), "10", "11", "9", "10", adjustment_semantics="unadjusted"),
        bar(date(2025, 11, 25), "10", "11", "9", "10"),
    ]
    first, second = resample(bars, "1wk", venue="XNYS", now=LATER)
    assert (first.source, first.adjustment_semantics) == ("mixed", "split_adjusted")
    assert (second.source, second.adjustment_semantics) == ("yfinance", "mixed")


def test_resample_refuses_other_intervals() -> None:
    with pytest.raises(ValueError):
        resample([], "1h", venue="XNYS", now=LATER)
    assert resample([], "1wk", venue="XNYS", now=LATER) == []
