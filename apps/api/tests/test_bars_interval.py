"""A1.4a: ``interval=1wk|1mo`` on the bars and indicators routers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services.bars import load as bars_load
from tests.symbols import seed_symbols

# Wednesday 19 Nov 2025, after New York's close: the week of 17 Nov is running.
NOW = datetime(2025, 11, 19, 23, tzinfo=UTC)
FIRST = date(2025, 6, 2)  # a Monday


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bars_load, "now_utc", lambda: NOW)


def _seed(session: Session, ticker: str = "AAPL", last: date = date(2025, 11, 19)) -> list[date]:
    """US weekday bars from 2 Jun 2025 to ``last``; close = 100 + index."""
    seed_symbols(session, ticker)
    days: list[date] = []
    day = FIRST
    while day <= last:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    for i, d in enumerate(days):
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime.combine(d, datetime.min.time()),
                interval="1d",
                open=Decimal(100 + i),
                high=Decimal(101 + i),
                low=Decimal(99 + i),
                close=Decimal(100 + i),
                volume=10,
                source="yfinance",
            )
        )
    session.commit()
    return days


def test_weekly_bars_count_output_bars_and_flag_the_running_week(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    response = client.get("/v1/symbols/AAPL/bars", params={"interval": "1wk", "limit": 3})
    assert response.status_code == 200, response.text
    bars = response.json()
    assert [b["ts"][:10] for b in bars] == ["2025-11-07", "2025-11-14", "2025-11-19"]
    assert [b["sessions"] for b in bars] == [5, 5, 3]
    assert [b["partial"] for b in bars] == [False, False, True]
    assert bars[0]["volume"] == 50
    assert bars[-1]["source"] == "yfinance" and bars[-1]["adjustment_semantics"] == "split_adjusted"
    # The week's open is Monday's, its close Wednesday's (so far).
    assert Decimal(bars[-1]["close"]) - Decimal(bars[-1]["open"]) == 2


def test_monthly_bars_and_a_long_limit(session: Session, client: TestClient) -> None:
    _seed(session)
    bars = client.get("/v1/symbols/AAPL/bars", params={"interval": "1mo", "limit": 100}).json()
    assert [b["ts"][:10] for b in bars] == [
        "2025-06-30",
        "2025-07-31",
        "2025-08-29",
        "2025-09-30",
        "2025-10-31",
        "2025-11-19",
    ]
    assert bars[0]["sessions"] == 21 and bars[0]["partial"] is False
    assert bars[-1]["partial"] is True


def test_from_and_to_select_bars_by_their_timestamp(session: Session, client: TestClient) -> None:
    _seed(session)
    bars = client.get(
        "/v1/symbols/AAPL/bars",
        # ``from`` mid-week keeps whole weeks; ``to`` mid-week drops that week.
        params={"interval": "1wk", "from": "2025-10-08", "to": "2025-10-22"},
    ).json()
    assert [(b["ts"][:10], b["sessions"]) for b in bars] == [("2025-10-10", 5), ("2025-10-17", 5)]


def test_daily_bars_are_unchanged_and_1h_is_refused(session: Session, client: TestClient) -> None:
    _seed(session)
    daily = client.get("/v1/symbols/AAPL/bars", params={"limit": 2}).json()
    assert [b["ts"][:10] for b in daily] == ["2025-11-18", "2025-11-19"]
    assert daily[0]["sessions"] is None and daily[0]["partial"] is None
    assert daily[0]["source"] == "yfinance"
    assert client.get("/v1/symbols/AAPL/bars", params={"interval": "1h"}).status_code == 422
    assert client.get("/v1/symbols/NOPE/bars", params={"interval": "1wk"}).status_code == 404


def test_weekly_indicators_warm_up_in_weeks_and_leave_out_the_partial_week(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    weekly = client.get("/v1/symbols/AAPL/bars", params={"interval": "1wk", "limit": 100}).json()
    closed = [Decimal(b["close"]) for b in weekly if not b["partial"]]

    body = client.get(
        "/v1/symbols/AAPL/indicators",
        params={"names": "sma_3", "interval": "1wk", "limit": 4},
    ).json()
    assert body["interval"] == "1wk"
    assert body["partial_bar_excluded"][:10] == "2025-11-19"
    assert body["warmup_bars"] == 2  # SMA 3 looks back two weeks
    points = body["series"]["sma_3"]
    # Four closed weeks in the window, each SMA over three weekly closes.
    assert [p["ts"][:10] for p in points] == [
        "2025-10-24",
        "2025-10-31",
        "2025-11-07",
        "2025-11-14",
    ]
    assert points[-1]["value"] == pytest.approx(float(sum(closed[-3:]) / 3))
    assert points[0]["value"] == pytest.approx(float(sum(closed[-6:-3]) / 3))


def test_indicators_on_a_closed_week_exclude_nothing(session: Session, client: TestClient) -> None:
    _seed(session, last=date(2025, 11, 14))
    body = client.get(
        "/v1/symbols/AAPL/indicators",
        params={"names": "sma_2", "interval": "1mo", "limit": 2},
    ).json()
    # November is still running on 19 Nov, so the monthly bar is left out.
    assert body["partial_bar_excluded"][:10] == "2025-11-14"
    weekly = client.get(
        "/v1/symbols/AAPL/indicators",
        params={"names": "sma_2", "interval": "1wk", "limit": 2},
    ).json()
    assert weekly["partial_bar_excluded"] is None
    assert weekly["series"]["sma_2"][-1]["ts"][:10] == "2025-11-14"
    assert (
        client.get(
            "/v1/symbols/AAPL/indicators", params={"names": "sma_2", "interval": "1h"}
        ).status_code
        == 422
    )
