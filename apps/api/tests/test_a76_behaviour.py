"""A7.6 (M10.4): behaviour diagnostics, by hand on synthetic outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.services.journal import behaviour as bh
from stockviz.services.journal.edge import Outcome
from tests.test_journal_entries import _h, _user

T0 = datetime(2026, 1, 5, 15, 0)  # 10:00 New York, a Monday


def _o(i: int, pnl: float, *, hold: int = 2, size: float = 1000.0, followed=None,
       opened: datetime | None = None, fees: float = 1.0, venue: str = "XNYS") -> Outcome:  # fmt: skip
    opened = opened or T0 + timedelta(days=i)
    return Outcome(entry_id=i, source="paper", currency="USD", net_pnl=pnl, r=None,
                   holding_days=hold, followed_plan=followed, fees_estimated=False,
                   closed_at=opened + timedelta(days=hold, hours=1), entry_date=opened.date(),
                   entry_notional=size, opened_at=opened, fees=fees, gross_pnl=pnl + fees,
                   venue=venue)  # fmt: skip


def test_disposition_discipline_and_costs_by_hand() -> None:
    # 30 entries: 15 winners held 2 days, 15 losers held 5 days.
    rows = [_o(i, 10.0 if i % 2 else -10.0, hold=2 if i % 2 else 5,
               followed=(i % 3 == 0) if i < 12 else None) for i in range(30)]  # fmt: skip
    out = bh.behaviour(rows)
    assert not out.counts_only
    assert (out.winners, out.losers) == (15, 15)
    assert out.disposition_index == 2.5  # 5 / 2
    assert out.discipline_scored == 12 and out.discipline_followed == 4
    assert out.discipline_rate == round(4 / 12, 4)
    assert out.fees_total == 30.0 and out.fees_per_entry == 1.0
    # Gross before fees: |11| x 15 + |-9| x 15 = 300; fees 30 -> 10%.
    assert out.fees_share_of_gross == 0.1


def test_tilt_needs_a_losing_close_and_a_size_spike() -> None:
    base = [_o(i, 5.0, hold=0) for i in range(6)]  # wins, size 1000
    loss = _o(6, -50.0, hold=0)
    spike = _o(7, 1.0, size=2000.0)  # after the loss, 2x the median
    calm = _o(8, 1.0, size=1200.0)
    assert bh.tilt_flags([*base, loss, spike, calm]) == [7]
    big_after_win = _o(7, 1.0, size=2000.0)
    assert bh.tilt_flags([*base, big_after_win]) == []


def test_heatmap_uses_the_venue_time_and_counts_only_under_30() -> None:
    monday_10 = _o(0, 5.0)  # 15:00 UTC = 10:00 New York, Monday 5 Jan
    indian = _o(2, -5.0, opened=datetime(2026, 1, 6, 4, 0), venue="XNSE")  # 09:30 IST, Tuesday
    out = bh.behaviour([monday_10, indian])
    assert out.counts_only and out.disposition_index is None and out.reason
    days = {c["key"]: c for c in out.by_weekday}
    assert days["Mon"]["entries"] == 1 and days["Tue"]["entries"] == 1
    assert [c["key"] for c in out.by_hour] == ["09:00", "10:00"]


def test_route_answers_for_an_empty_journal(session: Session, client: TestClient) -> None:
    uid = _user(session)
    body = client.get("/v1/journal/behaviour", headers=_h(uid)).json()
    assert body["entries"] == 0 and body["counts_only"] is True and "wording" in body["method"]
    assert client.get("/v1/journal/behaviour").status_code == 401
