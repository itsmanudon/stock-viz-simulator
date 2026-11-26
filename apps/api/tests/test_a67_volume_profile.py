"""A6.7 (M2.9): the volume profile, its route and the fixed-range drawing kind.

Synthetic bars only (never the owner's files). US times: in November New
York is UTC-5, so the 09:30 open is 14:30 UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.models.intraday import IntradayBar
from stockviz.services.bars.volume_profile import (
    BADGE_EOD,
    BADGE_IEX,
    BADGE_MINUTES,
    NoProfile,
    build_profile,
)
from stockviz.services.instruments import resolve_symbol
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

D = Decimal
MON = date(2025, 11, 24)
TUE = date(2025, 11, 25)


# --- the maths, by hand ------------------------------------------------------------


def test_poc_and_value_area_match_a_hand_calculation() -> None:
    """Five bins of 2 over 100-110.

    - A 100-110, 100 shares: 20 in each bin.
    - B 102-104, 60: all in bin 1 (102-104).
    - C 106-106, 30: no range, so all in the bin holding 106 (bin 3, 106-108).
    - D 103-105, 40: half in bin 1, half in bin 2 (104-106).

    Bins: 20, 100, 40, 50, 20 (total 230). POC bin 1 (102-104), price 103.
    Value area 70% = 161: from bin 1 (100), above 40 beats below 20 (140),
    then above 50 beats below 20 (190 >= 161). Bins 1-3: VAL 102, VAH 108.
    """
    bars = [(D(110), D(100), 100), (D(104), D(102), 60), (D(106), D(106), 30), (D(105), D(103), 40)]
    profile = build_profile(bars, bins=5, value_area=0.7)
    assert [b.low for b in profile.bins] == [D(100), D(102), D(104), D(106), D(108)]
    assert [b.high for b in profile.bins] == [D(102), D(104), D(106), D(108), D(110)]
    assert [round(b.volume, 6) for b in profile.bins] == [20, 100, 40, 50, 20]
    assert profile.total_volume == 230
    assert profile.poc == 1
    assert profile.poc_price == D(103)
    assert (profile.value_low, profile.value_high) == (1, 3)
    assert profile.val == D(102)
    assert profile.vah == D(108)
    assert round(profile.value_volume, 6) == 190


def test_value_area_ties_take_the_bin_above_and_full_area_takes_all() -> None:
    # Four bins of 1 over 0-4: 10, 40, 10, 10 -> POC bin 1; 50% = 35 is met at once.
    bars = [(D(1), D(0), 10), (D(2), D(1), 40), (D(3), D(2), 10), (D(4), D(3), 10)]
    tight = build_profile(bars, bins=4, value_area=0.5)
    assert (tight.value_low, tight.value_high) == (1, 1)
    # 70% = 49: below (10) and above (10) tie, so the bin above is taken first.
    seventy = build_profile(bars, bins=4, value_area=0.7)
    assert (seventy.value_low, seventy.value_high) == (1, 2)
    full = build_profile(bars, bins=4, value_area=1.0)
    assert (full.value_low, full.value_high) == (0, 3)


def test_poc_tie_goes_to_the_middle_then_lower() -> None:
    # Bins 0 and 3 tie at the top; neither is nearer the middle, so the lower wins.
    bars = [(D(1), D(0), 50), (D(2), D(1), 10), (D(3), D(2), 10), (D(4), D(3), 50)]
    assert build_profile(bars, bins=4).poc == 0
    # Bins 1 and 3 tie: bin 1 is 0.5 from the middle (1.5), bin 3 is 1.5 away.
    bars = [(D(1), D(0), 5), (D(2), D(1), 50), (D(3), D(2), 5), (D(4), D(3), 50)]
    assert build_profile(bars, bins=4).poc == 1


def test_one_price_is_one_bin_and_no_volume_is_no_profile() -> None:
    flat = build_profile([(D(5), D(5), 10), (D(5), D(5), 3)], bins=10)
    assert len(flat.bins) == 1
    assert flat.poc_price == D(5)
    with pytest.raises(NoProfile):
        build_profile([(D(5), D(4), 0)], bins=10)
    with pytest.raises(NoProfile):
        build_profile([], bins=10)


# --- the route -----------------------------------------------------------------------


def _instrument(session: Session, ticker: str = "AAPL") -> int:
    seed_symbols(session, ticker)
    instrument = resolve_symbol(session, ticker)
    assert instrument is not None and instrument.id is not None
    return instrument.id


def _daily(session: Session, ticker: str, day: date, *, volume: int = 1000) -> None:
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime.combine(day, time()),
            interval="1d",
            open=D(100),
            high=D(110),
            low=D(90),
            close=D(105),
            volume=volume,
            source="yfinance",
        )
    )
    session.commit()


def _minutes(session: Session, iid: int, day: date, *, feed: str, count: int = 30) -> None:
    start = datetime.combine(day, time(14, 30))
    for i in range(count):
        ts = start + timedelta(minutes=i)
        price = D(100) + D(i) / 10
        session.add(
            IntradayBar(
                instrument_id=iid,
                feed=feed,
                interval="1m",
                ts=ts,
                open=price,
                high=price + D("0.1"),
                low=price,
                close=price,
                volume=100,
                source=f"alpaca_{feed}",
                available_at=ts + timedelta(minutes=1),
            )
        )
    session.commit()


def _get(client: TestClient, ticker: str = "AAPL", **params: object):
    return client.get(f"/v1/symbols/{ticker}/volume-profile", params=params)


RANGE = {"from": "2025-11-24T00:00:00Z", "to": "2025-11-25T23:59:00Z", "bins": 10}


def test_minutes_that_cover_the_range_are_used(session: Session, client: TestClient) -> None:
    iid = _instrument(session)
    for day in (MON, TUE):
        _daily(session, "AAPL", day)
        _minutes(session, iid, day, feed="sip")
    body = _get(client, **RANGE).json()
    assert body["source"] == "minutes"
    assert body["feed"] == "sip"
    assert body["badges"] == [BADGE_MINUTES]
    assert body["bars"] == 60
    assert body["total_volume"] == 6000
    assert len(body["bins"]) == 10
    assert D(body["val"]) <= D(body["poc"]) <= D(body["vah"])
    assert "approximation" in body["note"]


def test_the_default_feed_is_sip_and_iex_is_labelled(session: Session, client: TestClient) -> None:
    iid = _instrument(session)
    _daily(session, "AAPL", MON)
    _minutes(session, iid, MON, feed="iex")
    iex_only = _get(client, **RANGE).json()
    assert iex_only["feed"] == "iex"
    assert iex_only["badges"] == [BADGE_MINUTES, BADGE_IEX]
    _minutes(session, iid, MON, feed="sip")
    assert _get(client, **RANGE).json()["feed"] == "sip"
    asked = _get(client, **RANGE, feed="iex").json()
    assert asked["feed"] == "iex"
    assert BADGE_IEX in asked["badges"]


def test_a_session_without_minutes_falls_back_to_daily(
    session: Session, client: TestClient
) -> None:
    iid = _instrument(session)
    _daily(session, "AAPL", MON)
    _daily(session, "AAPL", TUE)
    _minutes(session, iid, TUE, feed="sip")  # Monday has none
    body = _get(client, **RANGE).json()
    assert body["source"] == "daily"
    assert body["feed"] is None
    assert body["badges"] == [BADGE_EOD]
    assert body["bars"] == 2
    assert body["total_volume"] == 2000
    assert "daily bars" in body["note"]


def test_daily_only_symbol(session: Session, client: TestClient) -> None:
    _instrument(session)
    _daily(session, "AAPL", MON)
    body = _get(client, **RANGE).json()
    assert body["source"] == "daily"
    assert body["badges"] == [BADGE_EOD]
    # One bar spread over 90-110 in ten bins of 2: 100 each, POC in the middle.
    assert [b["volume"] for b in body["bins"]] == [100.0] * 10
    assert body["poc_index"] == 4


def test_an_index_gets_no_profile(session: Session, client: TestClient) -> None:
    iid = _instrument(session, "IDX")
    instrument = resolve_symbol(session, "IDX")
    assert instrument is not None
    instrument.asset_type = "index"
    session.add(instrument)
    session.commit()
    _daily(session, "IDX", MON, volume=0)
    _minutes(session, iid, MON, feed="sip")
    response = _get(client, "IDX", **RANGE)
    assert response.status_code == 409
    assert "index" in response.json()["detail"]
    detail = client.get("/v1/symbols/IDX").json()
    assert detail["is_index"] is True


def test_zero_volume_range_is_409(session: Session, client: TestClient) -> None:
    _instrument(session)
    _daily(session, "AAPL", MON, volume=0)
    response = _get(client, **RANGE)
    assert response.status_code == 409
    assert "no volume" in response.json()["detail"]
    assert client.get("/v1/symbols/AAPL").json()["is_index"] is False


def test_errors(session: Session, client: TestClient) -> None:
    assert _get(client, "NOPE", **RANGE).status_code == 404
    _instrument(session)
    assert _get(client, **RANGE).status_code == 404  # no bars at all
    _daily(session, "AAPL", MON)
    backwards = {**RANGE, "from": "2025-11-26T00:00:00Z"}
    assert _get(client, **backwards).status_code == 422
    assert _get(client, **{**RANGE, "bins": 2}).status_code == 422


# --- the fixed-range drawing kind ----------------------------------------------------------

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_volume_profile_drawing_is_two_dates(session: Session, client: TestClient) -> None:
    _instrument(session)
    for day in (MON, TUE):
        _daily(session, "AAPL", day)
    user = User(email="vp@x.dev", name="T")
    session.add(user)
    session.commit()
    uid = user.id
    assert uid is not None

    def post(points: list[dict]):
        return client.post(
            "/v1/drawings",
            json={"ticker": "AAPL", "kind": "volume_profile", "points": points},
            headers=_auth(uid),
        )

    ok = post([{"ts": "2025-11-25", "price": None}, {"ts": "2025-11-24", "price": None}])
    assert ok.status_code == 201, ok.text
    assert ok.json()["kind"] == "volume_profile"
    assert post([{"ts": "2025-11-24", "price": "100"}, {"ts": "2025-11-25"}]).status_code == 422
    assert post([{"ts": "2025-11-24"}]).status_code == 422
    assert post([{"ts": None}, {"ts": "2025-11-25"}]).status_code == 422
    assert post([{"ts": "2025-11-24"}, {"ts": "2025-12-25"}]).status_code == 422
