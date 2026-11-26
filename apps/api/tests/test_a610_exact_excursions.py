"""A6.10: exact MAE and MFE from stored minutes (worked by hand)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from stockviz.services.journal.roundtrips import (
    LedgerFill,
    MinuteBar,
    RoundTrip,
    minute_excursions,
)

D = Decimal
DAY = date(2026, 1, 6)


def _fill(side: str, qty: str, price: str, hhmm_ss: str) -> LedgerFill:
    h, m, s = (int(x) for x in hhmm_ss.split(":"))
    return LedgerFill(key=f"{side}{hhmm_ss}", side=side, quantity=D(qty), price=D(price),
                      fees=D(0), at=datetime(2026, 1, 6, h, m, s), venue_date=DAY)  # fmt: skip


def _minute(hhmm: str, low: str, high: str) -> MinuteBar:
    h, m = (int(x) for x in hhmm.split(":"))
    return MinuteBar(at=datetime(2026, 1, 6, h, m), day=DAY, high=D(high), low=D(low))


MINUTES = [
    _minute("15:00", "99", "101"),  # entry minute: the buy at 100 counts from its price
    _minute("15:01", "97", "100.5"),  # held: low 97 -> MAE -3
    _minute("15:02", "99", "104"),  # held: high 104 -> MFE +4
    _minute("15:03", "102", "108"),  # exit minute: shares sold at 103 count from that price
]


def test_long_entry_exact_to_the_minute() -> None:
    trip = RoundTrip(fills=[_fill("buy", "10", "100", "15:00:20"),
                            _fill("sell", "10", "103", "15:03:10")], closed=True)  # fmt: skip
    result = minute_excursions(trip, MINUTES, initial_risk=D("20"))
    assert result.basis == "exact_minutes" and result.mae and result.mfe
    # The shares held at 15:03's open saw its whole range (108), even though
    # they were sold inside that minute: exact to the minute, not the second.
    assert result.mae.per_share == D("-3") and result.mae.price == D("97")
    assert result.mfe.per_share == D("8") and result.mfe.price == D("108")
    assert result.mae.amount == D("-30") and result.mae.r == -1.5


def test_short_entry_mirrors() -> None:
    trip = RoundTrip(fills=[_fill("sell", "5", "100", "15:00:05"),
                            _fill("buy", "5", "98", "15:02:30")], closed=True, side="short")  # fmt: skip
    result = minute_excursions(trip, MINUTES[:3])
    assert result.mae and result.mfe
    assert result.mae.per_share == D("-4")  # high 104 in 15:02 while short from 100
    assert result.mfe.per_share == D("3")  # low 97 in 15:01


def test_no_minutes_is_unknown() -> None:
    trip = RoundTrip(fills=[_fill("buy", "1", "100", "15:00:00"),
                            _fill("sell", "1", "101", "15:01:00")], closed=True)  # fmt: skip
    result = minute_excursions(trip, [])
    assert result.mae is None and result.reason
