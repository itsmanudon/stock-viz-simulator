"""A6.2: intraday intervals on the bars, indicators, AVWAP and symbol routes.

Synthetic minutes only (never the owner's files). Times: IST = UTC + 5:30, so
09:15 IST is 03:45 UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models.intraday import IntradayBar
from stockviz.services.bars import intraday as intraday_mod
from stockviz.services.bars.intraday import resample_minutes
from stockviz.services.instruments import resolve_symbol
from tests.symbols import seed_symbols

IST = timedelta(hours=5, minutes=30)
TICKER = "TCS.NS"
# Long after every synthetic bar: nothing is partial unless a test says so.
LATER = datetime(2026, 11, 26, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: LATER)


def _utc(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m)) - IST


def _instrument(session: Session, ticker: str = TICKER) -> int:
    seed_symbols(session, ticker, currency="INR")
    instrument = resolve_symbol(session, ticker)
    assert instrument is not None and instrument.id is not None
    return instrument.id


def _minutes(
    session: Session,
    day: date,
    start: str,
    end: str,
    *,
    ticker: str = TICKER,
    base: float = 100.0,
    step: float = 0.0,
    volume: int = 10,
    feed: str = "file",
    skip_last: int = 0,
) -> list[datetime]:
    """1-minute bars from ``start`` to ``end`` IST (end exclusive); close = base + i x step."""
    iid = _instrument(session, ticker)
    ts = _utc(day, start)
    stop = _utc(day, end) - timedelta(minutes=skip_last)
    out: list[datetime] = []
    i = 0
    while ts < stop:
        close = Decimal(str(round(base + i * step, 4)))
        session.add(
            IntradayBar(
                instrument_id=iid,
                feed=feed,
                interval="1m",
                ts=ts,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=volume,
                source="bulk_1m",
                available_at=ts + timedelta(minutes=1),
            )
        )
        out.append(ts)
        ts += timedelta(minutes=1)
        i += 1
    session.commit()
    return out


def _hour(session: Session, day: date, start: str, end: str, close: str = "50") -> None:
    iid = _instrument(session)
    ts = _utc(day, start)
    session.add(
        IntradayBar(
            instrument_id=iid,
            feed="file",
            interval="60m",
            ts=ts,
            open=Decimal(close),
            high=Decimal(close) + 1,
            low=Decimal(close) - 1,
            close=Decimal(close),
            volume=600,
            source="bulk_1h",
            available_at=_utc(day, end),
        )
    )
    session.commit()


MON = date(2025, 11, 24)  # a regular NSE Monday
TUE = date(2025, 11, 25)
MUHURAT = date(2024, 11, 1)  # 18:00-19:00 IST
DR = date(2024, 3, 2)  # 09:15-10:00 and 11:30-12:30 IST


def _get(client: TestClient, interval: str, **params: object) -> list[dict]:
    response = client.get(f"/v1/symbols/{TICKER}/bars", params={"interval": interval, **params})
    assert response.status_code == 200, response.text
    return response.json()


# --- resampling within sessions ------------------------------------------------


def test_fifteen_and_sixty_minute_nse_day(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "09:15", "15:30", step=0.1)
    q15 = _get(client, "15m", limit=100)
    assert len(q15) == 25
    assert q15[-1]["ts"] == _utc(MON, "15:15").isoformat()
    assert q15[-1]["closed_at"] == _utc(MON, "15:30").isoformat()
    assert q15[0]["minutes"] == 15 and q15[0]["session_date"] == "2025-11-24"
    h = _get(client, "60m", limit=100)
    assert [b["ts"] for b in h] == [
        _utc(MON, t).isoformat()
        for t in ("09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15")
    ]
    last = h[-1]
    assert last["closed_at"] == _utc(MON, "15:30").isoformat() and last["minutes"] == 15
    # OHLCV of the first hour: first open, extremes, last close, summed volume.
    first = h[0]
    assert Decimal(first["open"]) == Decimal("100")
    assert Decimal(first["close"]) == Decimal("105.9")
    assert Decimal(first["high"]) == Decimal("106.9") and Decimal(first["low"]) == Decimal("99")
    assert first["volume"] == 600
    assert first["feed"] == "file" and first["badge"] == "File (local)"
    assert first["source"] == "bulk_1m" and first["partial"] is False


def test_no_bar_crosses_the_night(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "15:00", "15:30")
    _minutes(session, TUE, "09:15", "09:45")
    bars = _get(client, "60m")
    # The 14:15 bucket holds 15:00-15:14 only (it is clipped by data, not moved).
    assert [(b["ts"], b["closed_at"], b["minutes"]) for b in bars] == [
        (_utc(MON, "14:15").isoformat(), _utc(MON, "15:15").isoformat(), 15),
        (_utc(MON, "15:15").isoformat(), _utc(MON, "15:30").isoformat(), 15),
        (_utc(TUE, "09:15").isoformat(), _utc(TUE, "10:15").isoformat(), 30),
    ]
    five = _get(client, "5m", limit=1000)
    assert {b["session_date"] for b in five} == {"2025-11-24", "2025-11-25"}
    assert all(b["ts"][:10] == b["closed_at"][:10] for b in five)  # no bucket spans two days


def test_muhurat_evening_session(session: Session, client: TestClient) -> None:
    _minutes(session, MUHURAT, "18:00", "19:00")
    assert [(b["ts"], b["minutes"]) for b in _get(client, "60m")] == [
        (_utc(MUHURAT, "18:00").isoformat(), 60)
    ]
    q15 = _get(client, "15m")
    assert [b["ts"] for b in q15] == [
        _utc(MUHURAT, t).isoformat() for t in ("18:00", "18:15", "18:30", "18:45")
    ]
    assert q15[-1]["closed_at"] == _utc(MUHURAT, "19:00").isoformat()


def test_dr_session_pause_is_never_bridged(session: Session, client: TestClient) -> None:
    _minutes(session, DR, "09:15", "10:00")
    _minutes(session, DR, "11:30", "12:30")
    h = _get(client, "60m")
    assert [(b["ts"], b["closed_at"]) for b in h] == [
        (_utc(DR, "09:15").isoformat(), _utc(DR, "10:00").isoformat()),
        (_utc(DR, "11:30").isoformat(), _utc(DR, "12:30").isoformat()),
    ]
    assert [b["ts"] for b in _get(client, "30m")] == [
        _utc(DR, t).isoformat() for t in ("09:15", "09:45", "11:30", "12:00")
    ]


def test_minutes_outside_every_span_are_left_out() -> None:
    day = MON
    rows = [
        (
            _utc(day, "09:14"),
            Decimal(1),
            Decimal(1),
            Decimal(1),
            Decimal(1),
            1,
            "x",
            _utc(day, "09:15"),
        ),
        (
            _utc(day, "09:15"),
            Decimal(2),
            Decimal(2),
            Decimal(2),
            Decimal(2),
            1,
            "x",
            _utc(day, "09:16"),
        ),
    ]
    bars = resample_minutes(rows, "5m", venue="XNSE", feed="file")
    assert [(b.ts, b.minutes) for b in bars] == [(_utc(day, "09:15"), 1)]


# --- 60m precedence ----------------------------------------------------------------


def test_sixty_minutes_use_minutes_where_a_session_has_them_else_stored_hours(
    session: Session, client: TestClient
) -> None:
    old = date(2025, 11, 21)  # Friday: hourly bars only
    _hour(session, old, "09:15", "10:15", close="50")
    _hour(session, old, "15:15", "15:30", close="51")
    # Monday: both minutes and a stored hour; the minutes win for the session.
    _hour(session, MON, "09:15", "10:15", close="999")
    _minutes(session, MON, "09:15", "10:15")
    bars = _get(client, "60m")
    assert [(b["ts"], b["source"]) for b in bars] == [
        (_utc(old, "09:15").isoformat(), "bulk_1h"),
        (_utc(old, "15:15").isoformat(), "bulk_1h"),
        (_utc(MON, "09:15").isoformat(), "bulk_1m"),
    ]
    assert bars[1]["closed_at"] == _utc(old, "15:30").isoformat()
    assert Decimal(bars[2]["close"]) == Decimal("100")
    # Hourly bars cannot make 5m bars.
    only_hours = client.get("/v1/symbols/TCS.NS/bars", params={"interval": "5m"})
    assert only_hours.status_code == 200  # minutes exist on Monday


def test_hourly_only_symbol_refuses_minute_intervals(session: Session, client: TestClient) -> None:
    _hour(session, MON, "09:15", "10:15")
    response = client.get(f"/v1/symbols/{TICKER}/bars", params={"interval": "5m"})
    assert response.status_code == 404
    assert "no 1-minute bars" in response.json()["detail"]
    assert len(_get(client, "60m")) == 1


# --- partial newest bar -------------------------------------------------------------


def test_newest_bar_is_partial_until_it_closes(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minutes(session, MON, "09:15", "09:37")  # minutes up to 09:36 stored
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: _utc(MON, "09:37").replace(tzinfo=UTC))
    bars = _get(client, "15m")
    assert [b["partial"] for b in bars] == [False, True]
    assert bars[-1]["closed_at"] == _utc(MON, "09:45").isoformat()
    # After the close, a missing last minute keeps it open for the grace only.
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: _utc(MON, "09:46").replace(tzinfo=UTC))
    assert _get(client, "15m")[-1]["partial"] is True
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: _utc(MON, "10:30").replace(tzinfo=UTC))
    assert _get(client, "15m")[-1]["partial"] is False


def test_a_complete_newest_bar_is_not_partial_after_its_close(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minutes(session, MON, "09:15", "09:45")
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: _utc(MON, "09:45").replace(tzinfo=UTC))
    assert [b["partial"] for b in _get(client, "15m")] == [False, False]


# --- limits, from, to -----------------------------------------------------------------


def test_limit_counts_output_bars_and_from_to_select_by_open(
    session: Session, client: TestClient
) -> None:
    _minutes(session, MON, "09:15", "15:30")
    _minutes(session, TUE, "09:15", "15:30")
    last3 = _get(client, "30m", limit=3)
    assert [b["ts"] for b in last3] == [
        _utc(TUE, t).isoformat() for t in ("14:15", "14:45", "15:15")
    ]
    window = _get(
        client,
        "30m",
        **{"from": _utc(MON, "14:45").isoformat(), "to": _utc(TUE, "09:15").isoformat()},
    )
    assert [b["ts"] for b in window] == [
        _utc(MON, "14:45").isoformat(),
        _utc(MON, "15:15").isoformat(),
        _utc(TUE, "09:15").isoformat(),
    ]
    # The 09:15 bar is whole although ``to`` is its open.
    assert window[-1]["minutes"] == 30
    # An offset-aware ``to`` is the same instant.
    aware = _get(client, "30m", to="2025-11-25T09:15:00+05:30", limit=1)
    assert aware[0]["ts"] == _utc(TUE, "09:15").isoformat()


# --- empty and refused cases ----------------------------------------------------------------


def test_no_intraday_data_is_404_with_the_reason(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    response = client.get("/v1/symbols/AAPL/bars", params={"interval": "15m"})
    assert response.status_code == 404
    assert "No intraday bars are stored for AAPL" in response.json()["detail"]
    for path in ("indicators?names=sma_5&", "avwap?anchor=2025-11-24&"):
        r = client.get(f"/v1/symbols/AAPL/{path}interval=15m")
        assert r.status_code == 404, path


def test_unknown_feed_raw_and_bad_interval(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "09:15", "09:30")
    r = client.get(f"/v1/symbols/{TICKER}/bars", params={"interval": "5m", "feed": "iex"})
    assert r.status_code == 404 and "feed 'iex'" in r.json()["detail"]
    r = client.get(f"/v1/symbols/{TICKER}/bars", params={"interval": "5m", "adjustment": "raw"})
    assert r.status_code == 409
    r = client.get(f"/v1/symbols/{TICKER}/bars", params={"interval": "2m"})
    assert r.status_code == 422
    # A window with no bars is an empty list, not an error.
    assert _get(client, "5m", to="2020-01-01T00:00:00") == []


def test_feed_default_prefers_sip_over_file(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "09:15", "09:30", feed="file")
    _minutes(session, MON, "09:15", "09:20", feed="sip", base=200)
    bars = _get(client, "5m")
    assert {b["feed"] for b in bars} == {"sip"} and bars[0]["badge"] == "SIP"
    assert {b["feed"] for b in _get(client, "5m", feed="file")} == {"file"}


# --- symbol detail -------------------------------------------------------------------------------


def test_symbol_detail_lists_intraday_intervals(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    assert client.get("/v1/symbols/AAPL").json()["intraday"] is None
    _hour(session, date(2025, 11, 21), "09:15", "10:15")
    info = client.get(f"/v1/symbols/{TICKER}").json()["intraday"]
    assert info["intervals"] == ["60m"] and info["badge"] == "File (local)"
    assert info["venue"] == "XNSE" and info["time_zone"] == "Asia/Kolkata"
    _minutes(session, MON, "09:15", "09:30")
    info = client.get(f"/v1/symbols/{TICKER}").json()["intraday"]
    assert info["intervals"] == ["1m", "5m", "15m", "30m", "60m"]
    assert info["feed"] == "file" and info["feeds"] == ["file"]
    assert info["first"] == _utc(date(2025, 11, 21), "09:15").isoformat()
    assert info["last"] == _utc(MON, "09:29").isoformat()
    assert {(c["interval"], c["feed"]) for c in info["coverage"]} == {
        ("1m", "file"),
        ("60m", "file"),
    }


# --- indicators -----------------------------------------------------------------------------------


def test_indicators_warm_up_on_earlier_intraday_bars(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "09:15", "10:15", step=1)  # closes 100..159
    r = client.get(
        f"/v1/symbols/{TICKER}/indicators",
        params={"names": "sma_3", "interval": "5m", "limit": 2},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["interval"] == "5m" and body["feed"] == "file"
    assert body["warmup_bars"] == 2  # sma_3's lookback
    # 5m closes: 104, 109, ..., 159. The two window bars are 09:15+50 and +55.
    points = body["series"]["sma_3"]
    assert [p["ts"] for p in points] == [
        _utc(MON, "10:05").isoformat(),
        _utc(MON, "10:10").isoformat(),
    ]
    assert points[0]["value"] == pytest.approx((144 + 149 + 154) / 3)
    assert points[1]["value"] == pytest.approx((149 + 154 + 159) / 3)
    # The same value whatever the window size (warm-up, not the window start).
    wide = client.get(
        f"/v1/symbols/{TICKER}/indicators",
        params={"names": "sma_3", "interval": "5m", "limit": 12},
    ).json()["series"]["sma_3"]
    assert wide[-2]["value"] == pytest.approx(points[0]["value"])


def test_indicators_leave_out_a_partial_intraday_bar(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minutes(session, MON, "09:15", "09:52", step=1)
    monkeypatch.setattr(intraday_mod, "now_utc", lambda: _utc(MON, "09:52").replace(tzinfo=UTC))
    body = client.get(
        f"/v1/symbols/{TICKER}/indicators",
        params={"names": "sma_2", "interval": "15m"},
    ).json()
    assert body["partial_bar_excluded"] == _utc(MON, "09:45").isoformat()
    assert body["series"]["sma_2"][-1]["ts"] == _utc(MON, "09:30").isoformat()


def test_rs_line_is_empty_on_intraday(session: Session, client: TestClient) -> None:
    _minutes(session, MON, "09:15", "10:15")
    body = client.get(
        f"/v1/symbols/{TICKER}/indicators", params={"names": "rsline", "interval": "15m"}
    ).json()
    assert body["series"].get("rsline", []) == []


# --- AVWAP at an instant ----------------------------------------------------------------------------


def test_avwap_at_an_instant_on_minutes_and_sampled_on_five_minutes(
    session: Session, client: TestClient
) -> None:
    _minutes(session, MON, "09:15", "09:30", step=1)  # tp = close; equal volume
    anchor = _utc(MON, "09:17")
    r = client.get(
        f"/v1/symbols/{TICKER}/avwap",
        params={"interval": "1m", "anchor_at": anchor.isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["computed_from"] == "1m" and body["anchor_bar_at"] == anchor.isoformat()
    # tp = (H + L + C) / 3 = C; from 09:17 (close 102): running means.
    values = [p["vwap"] for p in body["points"]]
    assert values[:3] == [102.0, 102.5, 103.0]
    assert body["points"][0]["ts"] == anchor.isoformat()
    five = client.get(
        f"/v1/symbols/{TICKER}/avwap",
        params={"interval": "5m", "anchor_at": anchor.isoformat()},
    ).json()
    # Keyed by each 5m bar's open, valued at its last minute: 09:19 (102..104),
    # 09:24 (102..109), 09:29 (102..114).
    assert [p["ts"] for p in five["points"]] == [
        _utc(MON, t).isoformat() for t in ("09:15", "09:20", "09:25")
    ]
    assert [p["vwap"] for p in five["points"]] == [103.0, 105.5, 108.0]


def test_avwap_date_anchor_on_intraday_is_the_session_open(
    session: Session, client: TestClient
) -> None:
    _minutes(session, MON, "09:15", "09:20", step=2)
    body = client.get(
        f"/v1/symbols/{TICKER}/avwap", params={"interval": "15m", "anchor": "2025-11-24"}
    ).json()
    assert body["anchor_at"] == _utc(MON, "09:15").isoformat()
    assert body["points"] == [
        {
            "ts": _utc(MON, "09:15").isoformat(),
            "vwap": 104.0,
            "upper1": None,
            "lower1": None,
            "upper2": None,
            "lower2": None,
        }
    ]


def test_avwap_on_sixty_minutes_and_refusals(session: Session, client: TestClient) -> None:
    _hour(session, date(2025, 11, 21), "09:15", "10:15", close="50")
    _minutes(session, MON, "09:15", "10:15")
    body = client.get(
        f"/v1/symbols/{TICKER}/avwap",
        params={"interval": "60m", "anchor_at": _utc(date(2025, 11, 21), "09:15").isoformat()},
    ).json()
    assert body["computed_from"] == "60m"
    # Two bars: tp 50 x 600 and tp 100 x 600.
    assert [p["vwap"] for p in body["points"]] == [50.0, 75.0]
    r = client.get(f"/v1/symbols/{TICKER}/avwap", params={"interval": "15m"})
    assert r.status_code == 422
    r = client.get(
        f"/v1/symbols/{TICKER}/avwap",
        params={"interval": "15m", "anchor_at": "2030-01-01T00:00:00"},
    )
    assert r.status_code == 422
