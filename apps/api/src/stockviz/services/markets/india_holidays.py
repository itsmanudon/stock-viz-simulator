"""NSE and BSE trading holidays, maintained here (A0, workspace
``docs/stockviz-handover-2026-11-25.md``, "Calendar first").

The ``exchange_calendars`` package stops its BSE list at 31 Dec 2026 and has no
NSE calendar. This module owns the Indian holidays from 2026 onwards; years
before 2026 still come from the package (``calendar.py`` joins the two).

Each year is in one of two states:

- **Official:** the exchanges' published list for the year, copied into
  :data:`OFFICIAL_HOLIDAYS` with each holiday's name and the source checked.
- **Provisional:** no published list yet. Only the holidays that fall on the
  same date every year (:data:`FIXED_DATE_HOLIDAYS`) close the market. Lunar
  holidays (Holi, Eid, Diwali and the rest) are unknown, so a provisional year
  will treat those days as sessions until its official list is added here.

**Maintenance.** NSE and BSE publish the next year's list by circular, usually
in November or December. When they do, add the year to
:data:`OFFICIAL_HOLIDAYS` (every weekday holiday, with its name) and move
:data:`OFFICIAL_THROUGH` forward. Add any holiday announced during a year
(such as 15 Jan 2026, for the Maharashtra municipal elections) the same way.

NSE and BSE share one list: the 2026 list marks every trading holiday for both
exchanges. If they ever differ, add a per-venue override rather than a second
copy of the table.

Weekend holidays are left out: they close nothing.

**Special sessions.** The exchanges sometimes trade on a weekend (Budget
day, Diwali Muhurat trading, a live test of a new system or of the disaster
recovery site) or on a weekday holiday (Diwali Muhurat on Laxmi Pujan). :data:`SPECIAL_SESSIONS` lists each one with its source, and
the calendars count it as a session, so its daily bar is expected and not
reported as a bar on a closed day. Add a new one here when the exchanges
announce it.

**Special hours (A6.1).** A special session that did not trade the normal
09:15-15:30 has its hours in :data:`SPECIAL_HOURS` (the normal market's
continuous trading, IST, pre-open left out), so ``calendar.py`` gives it the
right open and close and the intraday loader accepts its minutes. A session
not listed there keeps the normal hours: the Budget days and the 20 Jan 2024
live session traded a full day.
"""

from __future__ import annotations

from datetime import date, time

FIRST_MAINTAINED_YEAR = 2026
"""Years before this come from the ``exchange_calendars`` BSE list."""

OFFICIAL_HOLIDAYS: dict[int, dict[date, str]] = {
    # 2026: NSE and BSE capital market segment. Checked on 25 Nov 2026 against
    # Zerodha's holiday calendar (zerodha.com/marketintel/holiday-calendar,
    # every entry marked for both NSE and BSE); it matches the BSE list in
    # exchange_calendars 4.13.2 date for date. Weekend holidays omitted:
    # Maha Shivaratri (15 Feb), Eid-Ul-Fitr (21 Mar), Independence Day
    # (15 Aug), Diwali Laxmi Pujan (8 Nov, Muhurat session).
    2026: {
        date(2026, 1, 15): "Municipal Corporation Elections in Maharashtra",
        date(2026, 1, 26): "Republic Day",
        date(2026, 3, 3): "Holi",
        date(2026, 3, 26): "Shri Ram Navami",
        date(2026, 3, 31): "Shri Mahavir Jayanti",
        date(2026, 4, 3): "Good Friday",
        date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
        date(2026, 5, 1): "Maharashtra Day",
        date(2026, 5, 28): "Bakri Eid",
        date(2026, 6, 26): "Moharram",
        date(2026, 9, 14): "Ganesh Chaturthi",
        date(2026, 10, 2): "Mahatma Gandhi Jayanti",
        date(2026, 10, 20): "Dussehra",
        date(2026, 11, 10): "Diwali Balipratipada",
        date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
        date(2026, 12, 25): "Christmas",
    },
}

OFFICIAL_THROUGH = 2026
"""The last year with an official list in :data:`OFFICIAL_HOLIDAYS`."""

PROVISIONAL_THROUGH = 2030
"""Provisional years run to the end of this year. After it, ``calendar.py``
falls back to the plain weekday rule, as for any date outside a calendar."""

FIXED_DATE_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 26): "Republic Day",
    (4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    (5, 1): "Maharashtra Day",
    (8, 15): "Independence Day",
    (10, 2): "Mahatma Gandhi Jayanti",
    (12, 25): "Christmas",
}
"""Holidays on the same date every year, closed on each official list from
2016 to 2026 whenever they fell on a weekday."""


def year_status(year: int) -> str:
    """``"official"``, ``"provisional"`` or ``"none"`` (outside the table)."""
    if FIRST_MAINTAINED_YEAR <= year <= OFFICIAL_THROUGH and year in OFFICIAL_HOLIDAYS:
        return "official"
    if OFFICIAL_THROUGH < year <= PROVISIONAL_THROUGH:
        return "provisional"
    return "none"


def holidays_for_year(year: int) -> dict[date, str]:
    """Weekday holidays in ``year``: the official list, or the fixed-date ones."""
    status = year_status(year)
    if status == "official":
        return dict(OFFICIAL_HOLIDAYS[year])
    if status == "provisional":
        days = {date(year, month, day): name for (month, day), name in FIXED_DATE_HOLIDAYS.items()}
        return {day: name for day, name in days.items() if day.weekday() < 5}
    return {}


def maintained_holidays() -> list[date]:
    """Every holiday this module owns, oldest first."""
    days: list[date] = []
    for year in range(FIRST_MAINTAINED_YEAR, PROVISIONAL_THROUGH + 1):
        days.extend(holidays_for_year(year))
    return sorted(days)


SPECIAL_SESSIONS: dict[date, str] = {
    # Each checked on 25 Nov 2026 against an NSE circular or a broker or
    # press notice; every one also has stored bars in production from more
    # than one ticker (yfinance and/or the Zerodha bulk files).
    date(2010, 2, 6): "Live session to test NSE's upgraded trading system (Business Standard)",
    date(2015, 2, 28): "Union Budget (Zerodha bulletin 52900)",
    date(2016, 10, 30): "Diwali Muhurat trading (Zerodha bulletin 53006, Business Standard)",
    date(2019, 10, 27): "Diwali Muhurat trading (NSE circular FAOP39613)",
    date(2020, 2, 1): "Union Budget (NSE circular FAOP43291)",
    date(2020, 11, 14): "Diwali Muhurat trading (NSE circular FAOP42878)",
    date(2023, 11, 12): "Diwali Muhurat trading (NSE circular COM54758)",
    date(2024, 1, 20): "Live session, planned as a disaster-recovery test (NSE)",
    date(
        2024, 3, 2
    ): "Live session with a switch to the disaster-recovery site (Zerodha bulletin 371327)",
    date(
        2024, 5, 18
    ): "Live session with a switch to the disaster-recovery site (Zerodha bulletin 377895)",
    date(2025, 2, 1): "Union Budget (Zerodha bulletin 400094)",
    date(2026, 2, 1): "Union Budget (Zerodha bulletin 439957)",
    # Weekday Muhurat sessions on the Laxmi Pujan holiday. Each checked on
    # 25 Nov 2026 against NSE circulars or broker and press notices, and each
    # has stored bars with real volume in production on 60+ tickers.
    date(2015, 11, 11): "Diwali Muhurat trading (Zerodha bulletin 52927, Business Standard)",
    date(2017, 10, 19): "Diwali Muhurat trading (NSE circular CMTR35993)",
    date(2018, 11, 7): "Diwali Muhurat trading (Zerodha bulletin 198876)",
    date(2021, 11, 4): "Diwali Muhurat trading (NSE circular CMTR50050)",
    date(2022, 10, 24): "Diwali Muhurat trading (Zerodha bulletin 334061)",
    date(2024, 11, 1): "Diwali Muhurat trading (NSE notification; Groww, Business Standard)",
    date(2025, 10, 21): "Diwali Muhurat trading (NSE circular; Business Standard)",
}
"""Days NSE and BSE traded outside their normal sessions: weekends, and
weekday holidays with a Muhurat session. Each counts as a session."""

SPECIAL_HOURS: dict[date, tuple[tuple[time, time], ...]] = {
    # Read on 26 Nov 2026 from the owner's 1-minute files (first and last
    # minute of every file on the day; no prices read): exact.
    date(2023, 11, 12): ((time(18, 15), time(19, 15)),),  # Muhurat
    date(2024, 3, 2): ((time(9, 15), time(10, 0)), (time(11, 30), time(12, 30))),  # DR switch
    date(2024, 5, 18): ((time(9, 15), time(10, 0)), (time(11, 30), time(12, 30))),  # DR switch
    date(2024, 11, 1): ((time(18, 0), time(19, 0)),),  # Muhurat
    date(2025, 10, 21): ((time(13, 45), time(14, 45)),),  # Muhurat, afternoon that year
    # Before the minute files (Jan 2023): the hours the exchanges announced,
    # as reported at the time; each agrees with the owner's hourly files
    # (bars start at those hours on those days and nowhere else). Not read
    # from a circular here: correct one if a circular disagrees.
    date(2015, 11, 11): ((time(17, 45), time(18, 45)),),  # Muhurat
    date(2016, 10, 30): ((time(18, 30), time(19, 30)),),  # Muhurat
    date(2017, 10, 19): ((time(18, 30), time(19, 30)),),  # Muhurat
    date(2018, 11, 7): ((time(17, 30), time(18, 30)),),  # Muhurat
    date(2019, 10, 27): ((time(18, 15), time(19, 15)),),  # Muhurat
    date(2020, 11, 14): ((time(18, 15), time(19, 15)),),  # Muhurat
    date(2021, 2, 24): ((time(9, 15), time(17, 0)),),  # NSE outage; close extended to 17:00
    date(2021, 11, 4): ((time(18, 15), time(19, 15)),),  # Muhurat
    date(2022, 10, 24): ((time(18, 15), time(19, 15)),),  # Muhurat
}
"""Sessions (special or regular) whose trading hours were not 09:15-15:30 IST:
one (open, close) span, or several when trading paused between them (the
live disaster-recovery switches). Open is the first minute, close the end of
the last one."""

HISTORY_CORRECTIONS: dict[date, bool] = {
    # The package's BSE list has Muharram 2013 on 14 Nov. The exchanges moved
    # it to 15 Nov two days before (Business Today, 13 Nov 2013; Business
    # Standard "Markets closed on account of Moharrum", 15 Nov 2013); every
    # stored bar on the 14th has real volume.
    date(2013, 11, 14): True,
    date(2013, 11, 15): False,
}
"""Dates where the package's history is wrong: True opens the day, False
closes it."""


def special_weekmasks() -> list[tuple[date, date, str]]:
    """One (Monday, Sunday, mask) per weekend special session's week, oldest first.

    The mask is the week's trading days, Monday first: weekdays open, plus
    the special day. Holidays in that week stay closed (they are listed
    separately).
    """
    masks: list[tuple[date, date, str]] = []
    for day in sorted(SPECIAL_SESSIONS):
        if day.weekday() < 5:
            continue  # a weekday opens by taking it off the holiday list
        monday = date.fromordinal(day.toordinal() - day.weekday())
        sunday = date.fromordinal(monday.toordinal() + 6)
        if masks and masks[-1][0] == monday:
            raise ValueError(f"two special sessions in the week of {monday}: merge their masks")
        mask = "".join("1" if i < 5 or i == day.weekday() else "0" for i in range(7))
        masks.append((monday, sunday, mask))
    return masks
