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

Weekend holidays are left out: they close nothing. Special sessions on a
weekend or holiday (Diwali Muhurat trading, a Budget-day session) are not
modelled: the daily-bar jobs do not use them.
"""

from __future__ import annotations

from datetime import date

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
