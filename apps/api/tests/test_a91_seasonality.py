"""A9.1 (M3.6, M6.6): seasonality and the post-earnings drift, by hand."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.models.earnings import EarningsEvent
from stockviz.services import seasonality as svc
from tests.symbols import seed_symbols


def test_monthly_returns_use_month_ends_and_skip_gaps() -> None:
    series = [(date(2024, 1, 31), 100.0), (date(2024, 2, 29), 110.0), (date(2024, 3, 28), 99.0),
              (date(2024, 6, 28), 120.0)]  # fmt: skip
    out = svc.seasonality(series)
    months = {m["key"]: m for m in out["months"]}  # type: ignore[union-attr]
    assert months["Feb"]["n"] == 1 and months["Feb"]["mean"] == 10.0
    assert months["Mar"]["mean"] == -10.0
    assert months["Jun"]["n"] == 0  # April and May missing: not a monthly return
    assert months["Feb"]["thin"] is True


def test_weekday_returns() -> None:
    series = [(date(2026, 1, 5), 100.0), (date(2026, 1, 6), 101.0), (date(2026, 1, 7), 99.99)]
    days = {d["key"]: d for d in svc.seasonality(series)["weekdays"]}  # type: ignore[union-attr]
    assert days["Tue"]["mean"] == 1.0 and days["Wed"]["mean"] == -1.0


def _event(day: date, when: str | None, surprise: float | None) -> EarningsEvent:
    return EarningsEvent(ticker="ACME", event_date=day, report_time=when,
                         surprise_pct=None if surprise is None else Decimal(str(surprise)))  # fmt: skip


def test_reaction_session_follows_the_report_time() -> None:
    dates = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    assert svc.reaction_index(dates, date(2026, 1, 6), "Before Market Open") == (1, False)
    assert svc.reaction_index(dates, date(2026, 1, 6), "After Market Close") == (2, False)
    assert svc.reaction_index(dates, date(2026, 1, 6), None) == (1, True)


def test_drift_by_hand() -> None:
    series = [(date(2026, 1, 5) + timedelta(days=i), 100.0 + i) for i in range(30)]
    series[10] = (series[10][0], 120.0)  # the reaction day jumps
    out = svc.earnings_drift(series, [_event(series[10][0], "BMO", 5.0)])
    (ev,) = out.events
    assert ev["reaction"] == round((120 / 109 - 1) * 100, 4)
    assert ev["d1"] == round((111 / 120 - 1) * 100, 4)
    beat = next(g for g in out.groups if g["group"] == "beat")
    assert beat["horizons"][0]["n"] == 1  # type: ignore[index]


def test_routes(session: Session, client: TestClient) -> None:
    seed_symbols(session, "ACME", currency="USD")
    start = datetime(2025, 1, 1)
    for i in range(400):
        price = Decimal(str(100 + (i % 7)))
        session.add(PriceBar(ticker="ACME", ts=start + timedelta(days=i), interval="1d", open=price,
                             high=price, low=price, close=price, volume=1, source="test"))  # fmt: skip
    session.add(EarningsEvent(ticker="ACME", event_date=date(2025, 6, 2), report_time="AMC",
                              surprise_pct=Decimal("-3")))  # fmt: skip
    session.commit()
    season = client.get("/v1/symbols/ACME/seasonality").json()
    assert len(season["months"]) == 12 and len(season["weekdays"]) == 5 and season["note"]
    drift = client.get("/v1/symbols/ACME/earnings-drift").json()
    (ev,) = drift["events"]
    assert ev["reaction_date"] == "2025-06-03" and ev["assumed"] is False
    assert drift["groups"][1]["group"] == "miss" and drift["groups"][1]["horizons"][0]["n"] == 1
    assert client.get("/v1/symbols/NOPE/seasonality").status_code == 404
