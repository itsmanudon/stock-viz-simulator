"""A3.1: ``GET /v1/symbols/{t}/bars?adjustment=raw`` reads ``eod_raw``.

RELIANCE.NS splits 1:2 on 17 Nov 2025 in this fixture: the adjusted
``price_bars`` sit near 1,000 throughout, the raw exchange rows near 2,000
before the split and 1,000 after it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import DataFile, PriceBar
from stockviz.models.eod import EodRaw
from stockviz.services.bars import load as bars_load
from stockviz.services.instruments import instrument_ids
from stockviz.services.markets.calendar import is_session
from tests.symbols import seed_symbols

SPLIT = date(2025, 11, 17)
# Wednesday 19 Nov 2025, after Mumbai's close: the week of 17 Nov is running.
NOW = datetime(2025, 11, 19, 23, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bars_load, "now_utc", lambda: NOW)


def _sessions(first: date, last: date) -> list[date]:
    days, day = [], first
    while day <= last:
        if is_session(day, "XNSE"):
            days.append(day)
        day += timedelta(days=1)
    return days


def _seed(session: Session) -> list[date]:
    seed_symbols(session, "RELIANCE.NS", currency="INR")
    seed_symbols(session, "AAPL")
    iid = instrument_ids(session, ["RELIANCE.NS"])["RELIANCE.NS"]
    session.add(
        DataFile(id=1, source="nse_cm_udiff", file_name="x.csv", sha256="0" * 64,
                 size_bytes=1, archived_path="x", parse_status="parsed")
    )  # fmt: skip
    session.flush()
    days = _sessions(date(2025, 11, 3), date(2025, 11, 19))
    for i, d in enumerate(days):
        adjusted = Decimal(1000 + i)
        raw = adjusted * (2 if d < SPLIT else 1)
        session.add(
            PriceBar(
                ticker="RELIANCE.NS", ts=datetime.combine(d, datetime.min.time()),
                interval="1d", open=adjusted, high=adjusted + 5, low=adjusted - 5,
                close=adjusted, volume=100, source="yfinance",
            )
        )  # fmt: skip
        session.add(
            EodRaw(
                instrument_id=iid, session_date=d, series="EQ", open=raw, high=raw + 10,
                low=raw - 10, close=raw, volume=50 * (2 if d >= SPLIT else 1),
                source="nse_cm_udiff", data_file_id=1,
            )
        )  # fmt: skip
    # A second series on one day loses to EQ; a BE-only day still has a bar.
    session.add(
        EodRaw(
            instrument_id=iid, session_date=days[0], series="BE", open=Decimal(1),
            high=Decimal(1), low=Decimal(1), close=Decimal(1), volume=1,
            source="nse_cm_udiff", data_file_id=1,
        )
    )  # fmt: skip
    session.add(
        EodRaw(
            instrument_id=iid, session_date=date(2025, 11, 1), series="BE",
            open=Decimal(1990), high=Decimal(1995), low=Decimal(1985), close=Decimal(1991),
            volume=7, source="nse_cm_udiff", data_file_id=1,
        )
    )  # fmt: skip
    session.commit()
    return days


def test_raw_daily_bars_are_the_exchange_numbers(session: Session, client: TestClient) -> None:
    days = _seed(session)
    adjusted = client.get("/v1/symbols/RELIANCE.NS/bars", params={"limit": 3}).json()
    raw = client.get(
        "/v1/symbols/RELIANCE.NS/bars", params={"limit": 3, "adjustment": "raw"}
    ).json()
    assert [b["ts"][:10] for b in raw] == [d.isoformat() for d in days[-3:]]
    assert [b["ts"] for b in raw] == [b["ts"] for b in adjusted]
    assert all(b["adjustment_semantics"] == "raw" for b in raw)
    assert raw[-1]["source"] == "nse_cm_udiff"
    assert adjusted[-1]["adjustment_semantics"] != "raw"

    # Across the split the raw close halves; the adjusted one does not.
    window = {"from": "2025-11-13", "to": "2025-11-18"}
    raw_window = client.get(
        "/v1/symbols/RELIANCE.NS/bars", params={**window, "adjustment": "raw"}
    ).json()
    adj_window = client.get("/v1/symbols/RELIANCE.NS/bars", params=window).json()
    before = next(b for b in raw_window if b["ts"][:10] == "2025-11-14")
    after = next(b for b in raw_window if b["ts"][:10] == "2025-11-17")
    assert Decimal(before["close"]) > Decimal(after["close"]) * Decimal("1.9")
    adj_closes = [Decimal(b["close"]) for b in adj_window]
    assert adj_closes == sorted(adj_closes)


def test_series_order_prefers_eq_and_falls_back(session: Session, client: TestClient) -> None:
    days = _seed(session)
    raw = client.get(
        "/v1/symbols/RELIANCE.NS/bars",
        params={"adjustment": "raw", "to": days[0].isoformat()},
    ).json()
    # 1 Nov is a BE-only row (a special session in this fixture's eyes); 3 Nov
    # has EQ and BE, and EQ wins.
    assert [b["ts"][:10] for b in raw] == ["2025-11-01", days[0].isoformat()]
    assert Decimal(raw[0]["close"]) == 1991
    assert Decimal(raw[1]["close"]) == Decimal(2000)


def test_raw_weekly_resamples_with_the_same_rules(session: Session, client: TestClient) -> None:
    _seed(session)
    weekly = client.get(
        "/v1/symbols/RELIANCE.NS/bars",
        params={"adjustment": "raw", "interval": "1wk", "limit": 2},
    ).json()
    assert [b["ts"][:10] for b in weekly] == ["2025-11-14", "2025-11-19"]
    assert [b["partial"] for b in weekly] == [False, True]
    assert weekly[-1]["sessions"] == 3
    assert weekly[-1]["adjustment_semantics"] == "raw"
    # The split week's raw volume is the sum of the doubled post-split volumes.
    assert weekly[-1]["volume"] == 300
    monthly = client.get(
        "/v1/symbols/RELIANCE.NS/bars",
        params={"adjustment": "raw", "interval": "1mo"},
    ).json()
    assert len(monthly) == 1 and monthly[0]["partial"] is True
    # Open is the first raw session's (the BE-only 1 Nov row), close the latest.
    assert Decimal(monthly[0]["open"]) == 1990


def test_no_raw_rows_is_409_and_has_raw_says_so(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/symbols/AAPL/bars", params={"adjustment": "raw"})
    assert response.status_code == 409
    assert "Only adjusted prices are stored for AAPL" in response.json()["detail"]
    assert client.get("/v1/symbols/AAPL").json()["has_raw"] is False
    assert client.get("/v1/symbols/RELIANCE.NS").json()["has_raw"] is True
    # The default stays adjusted, and other values are refused.
    assert client.get("/v1/symbols/AAPL/bars").status_code == 200
    assert client.get("/v1/symbols/AAPL/bars", params={"adjustment": "dividend"}).status_code == 422
    assert client.get("/v1/symbols/NOPE/bars", params={"adjustment": "raw"}).status_code == 404
