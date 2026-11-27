"""A6.9 (M9.4): replay with full orders. Synthetic bars and minutes only.

The acceptance (design note, "4. Acceptance", Replay):

- a bracket's stop and target cancel each other;
- when both fall inside one daily bar, the stop fills and the label shows;
- with minutes stored, the minute order decides;
- autoplay never double-advances (the ``expected_current_at`` guard), and
  advances are limited per user;
- the three-way kernel test passes for ``intrabar_ohlc``
  (``test_kernel_three_way.py``).

Plus intraday sessions (bars from stored minutes, the Indian lag on the end)
and daily sessions unchanged by default.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import PriceBar, ReplayFill, ReplayOrder, ReplaySession, User
from stockviz.models.intraday import IntradayBar
from stockviz.services.instruments import resolve_symbol
from stockviz.services.replay import (
    ReplayLagError,
    ReplayRangeError,
    advance_replay_session,
    create_replay_session,
)
from stockviz.services.replay import throttle as throttle_mod
from stockviz.services.replay.session import submit_replay_bracket
from stockviz.services.simulation import INTRABAR_UNKNOWN_LABEL, LEGACY_CLOSE_ASSUMPTIONS
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
D1, D2, D3 = datetime(2024, 6, 3), datetime(2024, 6, 4), datetime(2024, 6, 5)
US_OPEN = datetime(2024, 6, 4, 13, 30)  # 09:30 New York, naive UTC
D = Decimal


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {jose_jwt.encode({'sub': str(user_id)}, SECRET, 'HS256')}"}


def _user(session: Session, email: str = "a69@stockviz.dev") -> int:
    row = User(email=email, name="A69")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def _daily(session: Session, bars: dict[datetime, tuple[str, str, str, str]], ticker="AAPL"):
    seed_symbols(session, ticker, currency="INR" if ticker.endswith(".NS") else "USD")
    for ts, (o, h, lo, c) in bars.items():
        session.add(PriceBar(ticker=ticker, ts=ts, interval="1d", open=D(o), high=D(h),
                             low=D(lo), close=D(c), volume=1000, source="test"))  # fmt: skip
    session.commit()


def _minutes(session: Session, start: datetime, rows: list[tuple[str, str, str, str]],
             ticker: str = "AAPL", feed: str = "file") -> None:  # fmt: skip
    """1-minute bars from ``start`` (naive UTC), one per row of (o, h, l, c)."""
    instrument = resolve_symbol(session, ticker)
    assert instrument is not None and instrument.id is not None
    for i, (o, h, lo, c) in enumerate(rows):
        ts = start + timedelta(minutes=i)
        session.add(IntradayBar(instrument_id=instrument.id, feed=feed, interval="1m", ts=ts,
                                open=D(o), high=D(h), low=D(lo), close=D(c), volume=10,
                                source="bulk_1m", available_at=ts + timedelta(minutes=1)))  # fmt: skip
    session.commit()


def _create(client, headers, **extra):
    body = {"ticker": "AAPL", "start_at": D1.isoformat(), "end_at": D3.isoformat(),
            "profile": "intrabar_ohlc", **extra}  # fmt: skip
    response = client.post("/v1/replay/sessions", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _bracket(client, headers, sid, **extra):
    body = {"side": "buy", "order_type": "bracket", "quantity": "10", "entry_type": "market",
            "stop_price": "95", "target_price": "105", **extra}  # fmt: skip
    return client.post(f"/v1/replay/sessions/{sid}/orders", headers=headers, json=body)


def _advance(client, headers, sid, current_at):
    return client.post(f"/v1/replay/sessions/{sid}/advance", headers=headers,
                       params={"expected_current_at": current_at})  # fmt: skip


def _orders(client, headers, sid) -> dict[str, dict]:
    rows = client.get(f"/v1/replay/sessions/{sid}/orders", headers=headers).json()
    return {row["order_type"]: row for row in rows}


FLAT = ("100", "100", "100", "100")


def test_market_bracket_target_cancels_stop(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "106", "99", "105"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    placed = _bracket(client, headers, sid)
    assert placed.status_code == 200, placed.text
    body = placed.json()
    entry = body["order"]
    assert entry["order_type"] == "bracket" and entry["status"] == "filled"
    assert body["fill"]["fill_price"] == "100.000000"
    children = {c["order_type"]: c for c in body["children"]}
    assert set(children) == {"stop_loss", "take_profit"}
    for child in children.values():
        assert child["status"] == "open"
        assert child["parent_id"] == entry["id"] and child["oco_group"] == entry["id"]
    assert entry["oco_group"] == entry["id"]

    moved = _advance(client, headers, sid, body["session"]["current_at"])
    assert moved.status_code == 200
    orders = _orders(client, headers, sid)
    assert orders["take_profit"]["status"] == "filled"
    assert orders["stop_loss"]["status"] == "cancelled"
    assert "One cancels the other: the target filled" in orders["stop_loss"]["reason"]
    assert orders["take_profit"]["order_inside_bar_unknown"] is False
    fill = session.exec(
        select(ReplayFill).where(ReplayFill.order_id == orders["take_profit"]["id"])
    ).one()
    assert fill.fill_price == D("105") and fill.profile_name == "intrabar_ohlc"
    assert moved.json()["positions"] == []


def test_market_bracket_stop_cancels_target(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "101", "94", "96"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _bracket(client, headers, sid).json()
    _advance(client, headers, sid, body["session"]["current_at"])
    orders = _orders(client, headers, sid)
    assert orders["stop_loss"]["status"] == "filled"
    assert orders["take_profit"]["status"] == "cancelled"
    assert "the stop filled" in orders["take_profit"]["reason"]


def test_both_inside_one_daily_bar_stop_fills_labelled(
    session: Session, client: TestClient
) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "106", "94", "105"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _bracket(client, headers, sid).json()
    _advance(client, headers, sid, body["session"]["current_at"])
    orders = _orders(client, headers, sid)
    stop = orders["stop_loss"]
    assert stop["status"] == "filled" and stop["order_inside_bar_unknown"] is True
    assert INTRABAR_UNKNOWN_LABEL in stop["reason"]
    assert orders["take_profit"]["status"] == "cancelled"
    fills = client.get(f"/v1/replay/sessions/{sid}/fills", headers=headers).json()
    exit_fill = next(f for f in fills if f["order_id"] == stop["id"])
    assert exit_fill["fill_price"] == "95.000000"
    assert exit_fill["reason"].startswith(INTRABAR_UNKNOWN_LABEL)


def test_minutes_stored_the_minute_order_decides(session: Session, client: TestClient) -> None:
    """The same daily bar, with its session's minutes stored: the target is
    reached in the third minute and the stop later, so the target fills."""
    _daily(session, {D1: FLAT, D2: ("100", "106", "94", "105"), D3: FLAT})
    _minutes(session, US_OPEN, [("100", "101", "99", "100"), ("100", "103", "99", "102"),
                                ("102", "106", "101", "104"), ("104", "104", "94", "96"),
                                ("96", "105", "95", "105")])  # fmt: skip
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _bracket(client, headers, sid).json()
    _advance(client, headers, sid, body["session"]["current_at"])
    orders = _orders(client, headers, sid)
    assert orders["take_profit"]["status"] == "filled"
    assert orders["take_profit"]["order_inside_bar_unknown"] is False
    assert "stored minutes decide" in orders["take_profit"]["reason"]
    assert orders["stop_loss"]["status"] == "cancelled"


def test_minutes_stop_first_when_they_say_so(session: Session) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "106", "94", "105"), D3: FLAT})
    _minutes(session, US_OPEN, [("100", "100", "94", "95"), ("95", "106", "95", "105")])
    uid = _user(session)
    replay = create_replay_session(session, user_id=uid, ticker="AAPL", start_at=D1, end_at=D3,
                                   profile="intrabar_ohlc")  # fmt: skip
    submit_replay_bracket(session, replay=replay, quantity=D(10), entry_type="market",
                          stop_price=D(95), target_price=D(105))  # fmt: skip
    advance_replay_session(session, replay=replay)
    rows = {o.order_type: o for o in session.exec(select(ReplayOrder)).all()}
    assert rows["stop_loss"].status == "filled"
    assert INTRABAR_UNKNOWN_LABEL not in (rows["stop_loss"].reason or "")


def test_limit_bracket_children_rest_only_after_the_entry(
    session: Session, client: TestClient
) -> None:
    d4 = datetime(2024, 6, 6)
    _daily(session, {D1: FLAT, D2: ("100", "101", "97", "99"), D3: ("99", "103", "90", "92"),
                     d4: FLAT})  # fmt: skip
    headers = _headers(_user(session))
    sid = _create(client, headers, end_at=d4.isoformat())["id"]
    placed = _bracket(client, headers, sid, entry_type="limit", limit_price="98")
    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert body["fill"] is None and body["order"]["status"] == "open"
    assert {c["status"] for c in body["children"]} == {"pending"}

    day2 = _advance(client, headers, sid, body["session"]["current_at"]).json()
    orders = _orders(client, headers, sid)
    assert orders["bracket"]["status"] == "filled"  # the low (97) reached the limit (98)
    assert {orders["stop_loss"]["status"], orders["take_profit"]["status"]} == {"open"}
    assert day2["positions"][0]["quantity"] == "10.000000"

    _advance(client, headers, sid, day2["current_at"])
    orders = _orders(client, headers, sid)
    assert orders["stop_loss"]["status"] == "filled"  # 90 < 95, open 99 above it: at 95
    assert orders["take_profit"]["status"] == "cancelled"


def test_cancel_unfilled_entry_cancels_its_children(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _bracket(client, headers, sid, entry_type="limit", limit_price="98").json()
    entry_id = body["order"]["id"]
    cancelled = client.post(f"/v1/replay/sessions/{sid}/orders/{entry_id}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert {o["status"] for o in _orders(client, headers, sid).values()} == {"cancelled"}
    # A pending child can be cancelled too; a cancelled one is not open.
    again = client.post(
        f"/v1/replay/sessions/{sid}/orders/{body['children'][0]['id']}/cancel", headers=headers
    )
    assert again.status_code == 409


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"stop_price": "101"}, "stop must be below"),
        ({"target_price": "99"}, "stop must be below"),
        ({"target_price": None}, "positive stop and a positive target"),
        ({"side": "sell"}, "long bracket's entry is a buy"),
        ({"entry_type": "limit", "limit_price": "94"}, "stop must be below the limit"),
        ({"entry_type": "limit"}, "limit entry needs a positive limit"),
    ],
)
def test_bracket_validation(session: Session, client: TestClient, extra, message) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    response = _bracket(client, headers, sid, **extra)
    assert response.status_code == 400 and message in response.json()["detail"]
    assert client.get(f"/v1/replay/sessions/{sid}/orders", headers=headers).json() == []
    assert client.get(f"/v1/replay/sessions/{sid}/fills", headers=headers).json() == []


def test_legacy_close_bracket_on_closes(session: Session, client: TestClient) -> None:
    """Under legacy_close the children trigger on the close only."""
    _daily(session, {D1: FLAT, D2: ("100", "106", "94", "100"), D3: ("100", "106", "100", "106")})
    headers = _headers(_user(session))
    sid = _create(client, headers, profile="legacy_close")["id"]
    body = _bracket(client, headers, sid).json()
    day2 = _advance(client, headers, sid, body["session"]["current_at"]).json()
    assert {o["status"] for o in _orders(client, headers, sid).values()} == {"filled", "open"}
    _advance(client, headers, sid, day2["current_at"])
    orders = _orders(client, headers, sid)
    assert orders["take_profit"]["status"] == "filled"
    assert orders["stop_loss"]["status"] == "cancelled"


def test_daily_session_default_is_unchanged(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    body = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={
            "ticker": "AAPL",
            "start_at": D1.isoformat(),
            "end_at": D3.isoformat(),
            "profile": "legacy_close",
        },
    ).json()
    assert (body["profile_name"], body["model_version"], body["interval"]) == (
        "legacy_close",
        "v1",
        "1d",
    )
    assert body["feed"] is None
    assert body["profile_assumptions"] == list(LEGACY_CLOSE_ASSUMPTIONS)
    listed = client.get("/v1/replay/sessions", headers=headers).json()[0]
    assert (listed["interval"], listed["profile_name"]) == ("1d", "legacy_close")
    bad = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": D1.isoformat(), "profile": "next_open"},
    )
    assert bad.status_code == 422


def test_autoplay_never_double_advances(session: Session, client: TestClient) -> None:
    """Autoplay sends the bar on screen with every step. A step repeated
    with a stale bar (a doubled click, a retried call, a timer firing twice)
    changes nothing, so N steps move N bars, never more."""
    days = [datetime(2024, 6, 3) + timedelta(days=i) for i in range(12)]
    _daily(session, dict.fromkeys(days, FLAT))
    headers = _headers(_user(session))
    created = _create(client, headers, end_at=days[-1].isoformat())
    sid, current = created["id"], created["current_at"]
    for step in range(10):
        first = _advance(client, headers, sid, current).json()
        repeat = _advance(client, headers, sid, current).json()  # the same bar again
        assert repeat["current_at"] == first["current_at"]
        assert datetime.fromisoformat(first["current_at"]).replace(tzinfo=None) == days[step + 1]
        current = first["current_at"]
    history = client.get(f"/v1/replay/sessions/{sid}/history", headers=headers).json()
    assert len(history) == 11


def test_advance_is_rate_limited_per_user(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stockviz.limiter import limiter

    clock = [100.0]
    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(
        throttle_mod,
        "ADVANCE_THROTTLE",
        throttle_mod.AdvanceThrottle(limit=3, window=1.0, clock=lambda: clock[0]),
    )
    import stockviz.routers.replay as replay_router

    monkeypatch.setattr(replay_router, "ADVANCE_THROTTLE", throttle_mod.ADVANCE_THROTTLE)
    days = [datetime(2024, 6, 3) + timedelta(days=i) for i in range(8)]
    _daily(session, dict.fromkeys(days, FLAT))
    a, b = _user(session), _user(session, "a69-b@stockviz.dev")
    ha, hb = _headers(a), _headers(b)
    sid = _create(client, ha, end_at=days[-1].isoformat())["id"]
    other = _create(client, hb, end_at=days[-1].isoformat())["id"]
    advance = f"/v1/replay/sessions/{sid}/advance"
    for _ in range(3):
        assert client.post(advance, headers=ha).status_code == 200
    refused = client.post(advance, headers=ha)
    assert refused.status_code == 429 and refused.headers["Retry-After"] == "1"
    session.expire_all()
    stored = session.get(ReplaySession, sid)
    assert stored is not None and stored.current_at == days[3]  # the refused step moved nothing
    assert client.post(f"/v1/replay/sessions/{other}/advance", headers=hb).status_code == 200
    clock[0] += 1.0
    assert client.post(advance, headers=ha).status_code == 200


# --- intraday sessions --------------------------------------------------------


def _five_minute_day(session: Session) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    rows = [(str(100 + i), str(101 + i), str(99 + i), str(100 + i)) for i in range(60)]
    _minutes(session, US_OPEN, rows)


def test_intraday_session_on_five_minute_bars(session: Session, client: TestClient) -> None:
    _five_minute_day(session)
    headers = _headers(_user(session))
    available = client.get("/v1/replay/availability", headers=headers, params={"ticker": "AAPL"})
    assert available.json()["intervals"] == ["1d", "1m", "5m", "15m", "60m"]
    assert available.json()["minute_feed"] == "file"
    end = US_OPEN + timedelta(minutes=55)
    body = _create(client, headers, interval="5m", start_at=US_OPEN.isoformat(),
                   end_at=end.isoformat())  # fmt: skip
    assert (body["interval"], body["feed"], body["profile_name"]) == ("5m", "file", "intrabar_ohlc")
    sid = body["id"]
    market = client.get(f"/v1/replay/sessions/{sid}/market", headers=headers).json()
    bar = market["bar"]
    assert bar["interval"] == "5m"
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (
        "100.000000", "105.000000", "99.000000", "104.000000"
    )  # fmt: skip
    moved = _advance(client, headers, sid, body["current_at"]).json()
    assert datetime.fromisoformat(moved["current_at"]).replace(tzinfo=None) == US_OPEN + timedelta(
        minutes=5
    )
    history = client.get(f"/v1/replay/sessions/{sid}/history", headers=headers).json()
    assert len(history) == 2  # never a bar after the clock
    current = moved["current_at"]
    for _ in range(10):
        current = _advance(client, headers, sid, current).json()["current_at"]
    finished = _advance(client, headers, sid, current).json()
    assert finished["status"] == "completed"
    assert len(client.get(f"/v1/replay/sessions/{sid}/history", headers=headers).json()) == 12


def test_intraday_bracket_minutes_inside_the_bar_decide(session: Session) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    flat = [("100", "100", "100", "100")] * 5
    # The second 5-minute bar reaches both 95 and 105: the target in its
    # second minute, the stop in its fourth.
    second = [("100", "101", "99", "100"), ("100", "106", "100", "104"),
              ("104", "104", "100", "100"), ("100", "100", "94", "96"), ("96", "97", "95", "96")]  # fmt: skip
    _minutes(session, US_OPEN, flat + second + flat)
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="AAPL", start_at=US_OPEN,
        end_at=US_OPEN + timedelta(minutes=10), interval="5m", profile="intrabar_ohlc",
    )  # fmt: skip
    submit_replay_bracket(session, replay=replay, quantity=D(10), entry_type="market",
                          stop_price=D(95), target_price=D(105))  # fmt: skip
    advance_replay_session(session, replay=replay)
    rows = {o.order_type: o for o in session.exec(select(ReplayOrder)).all()}
    assert rows["take_profit"].status == "filled" and rows["stop_loss"].status == "cancelled"
    fill = session.exec(
        select(ReplayFill).where(ReplayFill.order_id == rows["take_profit"].id)
    ).one()
    assert fill.market_interval == "5m" and fill.fill_price == D(105)


def test_one_minute_bracket_both_inside_stop_first(session: Session) -> None:
    """A 1-minute bar has nothing finer: both inside it, the stop fills, labelled."""
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    _minutes(session, US_OPEN, [FLAT, ("100", "106", "94", "100"), FLAT])
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="AAPL", start_at=US_OPEN,
        end_at=US_OPEN + timedelta(minutes=2), interval="1m", profile="intrabar_ohlc",
    )  # fmt: skip
    submit_replay_bracket(session, replay=replay, quantity=D(10), entry_type="market",
                          stop_price=D(95), target_price=D(105))  # fmt: skip
    advance_replay_session(session, replay=replay)
    rows = {o.order_type: o for o in session.exec(select(ReplayOrder)).all()}
    assert rows["stop_loss"].status == "filled"
    assert INTRABAR_UNKNOWN_LABEL in (rows["stop_loss"].reason or "")


def test_intraday_needs_minutes_and_enough_bars(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    assert client.get("/v1/replay/availability", headers=headers, params={"ticker": "AAPL"}).json()[
        "intervals"
    ] == ["1d"]
    response = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": US_OPEN.isoformat(),
              "end_at": (US_OPEN + timedelta(hours=1)).isoformat(), "interval": "5m"},
    )  # fmt: skip
    assert response.status_code == 400 and "No minute bars" in response.json()["detail"]
    _minutes(session, US_OPEN, [FLAT] * 30)
    one_bar = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": US_OPEN.isoformat(),
              "end_at": (US_OPEN + timedelta(minutes=29)).isoformat(), "interval": "60m"},
    )  # fmt: skip
    assert one_bar.status_code == 400 and "at least 2" in one_bar.json()["detail"]


def test_indian_lag_applies_to_an_intraday_end(session: Session) -> None:
    """The 30-day lag reads the end bar's venue date (IST)."""
    _daily(session, {datetime(2025, 11, 19): FLAT, datetime(2025, 11, 20): FLAT}, ticker="TCS.NS")
    open_ist = datetime(2025, 11, 20, 3, 45)  # 09:15 IST
    _minutes(session, open_ist, [FLAT] * 30, ticker="TCS.NS")
    uid = _user(session)
    kwargs = {
        "user_id": uid,
        "ticker": "TCS.NS",
        "start_at": open_ist,
        "end_at": open_ist + timedelta(minutes=29),
        "interval": "15m",
    }
    with pytest.raises(ReplayLagError, match="30 days"):
        create_replay_session(session, today=date(2025, 12, 1), **kwargs)  # type: ignore[arg-type]
    replay = create_replay_session(session, today=date(2026, 1, 15), **kwargs)  # type: ignore[arg-type]
    assert replay.interval == "15m" and replay.currency == "INR"
    with pytest.raises(ReplayRangeError):
        create_replay_session(session, today=date(2026, 1, 15), **{**kwargs, "end_at": None})  # type: ignore[arg-type]


def test_intraday_sell_pays_dp_once_per_venue_day(session: Session) -> None:
    """Fees on an intraday session price on the bar's IST date, and the DP
    charge is due once per day however many bars it has."""
    _daily(session, {datetime(2025, 11, 19): FLAT, datetime(2025, 11, 20): FLAT}, ticker="TCS.NS")
    open_ist = datetime(2025, 11, 20, 3, 45)
    _minutes(session, open_ist, [FLAT] * 15, ticker="TCS.NS")
    from stockviz.services.replay import submit_replay_order
    from stockviz.services.simulation import OrderSide, SimulationOrderType

    uid = _user(session)
    replay = create_replay_session(session, user_id=uid, ticker="TCS.NS", start_at=open_ist,
                                   end_at=open_ist + timedelta(minutes=14), interval="5m",
                                   today=date(2026, 1, 15))  # fmt: skip
    submit_replay_order(session, replay=replay, side=OrderSide.BUY,
                        order_type=SimulationOrderType.MARKET, quantity=D(10))  # fmt: skip
    first = submit_replay_order(session, replay=replay, side=OrderSide.SELL,
                                order_type=SimulationOrderType.MARKET, quantity=D(5)).fill  # fmt: skip
    replay = advance_replay_session(session, replay=replay)
    second = submit_replay_order(session, replay=replay, side=OrderSide.SELL,
                                 order_type=SimulationOrderType.MARKET, quantity=D(5)).fill  # fmt: skip
    assert first is not None and second is not None
    dp = [
        any(line.get("key") == "dp_charge" for line in (f.fee_lines or [])) for f in (first, second)
    ]
    assert dp == [True, False]


def test_session_out_names_the_profile(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    body = _create(client, headers)
    assert body["profile_name"] == "intrabar_ohlc"
    assert any("open comes first" in a for a in body["profile_assumptions"])
    stored = session.get(ReplaySession, body["id"])
    assert stored is not None and stored.profile_name == "intrabar_ohlc"


def test_new_sessions_default_to_intrabar_ohlc(session: Session, client: TestClient) -> None:
    """Owner, 27 Nov 2026: a session opened without a profile uses intrabar_ohlc."""
    _daily(session, {D1: FLAT, D2: FLAT})
    headers = _headers(_user(session))
    created = _create(client, headers, profile=None)
    assert created["profile_name"] == "intrabar_ohlc"


# Short brackets (owner, 27 Nov 2026): US-listed only; the entry sells short,
# the stop above and the target below are buys that cover.
def _short(client, headers, sid, **extra):
    return _bracket(client, headers, sid, side="sell", direction="short", stop_price="105",
                    target_price="95", **extra)  # fmt: skip


def test_short_market_bracket_target_covers(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "101", "94", "96"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    placed = _short(client, headers, sid)
    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert body["order"]["side"] == "sell" and body["fill"]["side"] == "sell"
    assert {c["side"] for c in body["children"]} == {"buy"}
    held = client.get(f"/v1/replay/sessions/{sid}", headers=headers).json()
    assert held["positions"][0]["quantity"] == "-10.000000"
    moved = _advance(client, headers, sid, body["session"]["current_at"])
    assert moved.status_code == 200, moved.text
    orders = _orders(client, headers, sid)
    assert orders["take_profit"]["status"] == "filled"
    assert orders["stop_loss"]["status"] == "cancelled"
    fill = session.exec(
        select(ReplayFill).where(ReplayFill.order_id == orders["take_profit"]["id"])
    ).one()
    assert fill.side == "buy" and fill.fill_price == D("95")
    assert fill.realized_pnl == D("50")  # (100 - 95) x 10
    assert moved.json()["positions"] == []


def test_short_market_bracket_stop_covers_at_a_loss(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "106", "99", "104"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _short(client, headers, sid).json()
    _advance(client, headers, sid, body["session"]["current_at"])
    orders = _orders(client, headers, sid)
    assert orders["stop_loss"]["status"] == "filled"
    fill = session.exec(
        select(ReplayFill).where(ReplayFill.order_id == orders["stop_loss"]["id"])
    ).one()
    assert fill.fill_price == D("105") and fill.realized_pnl == D("-50")


def test_short_limit_bracket_rests_then_sells(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: ("100", "103", "99", "101"), D3: ("101", "102", "94", "95")})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _short(client, headers, sid, entry_type="limit", limit_price="102").json()
    assert body["order"]["status"] == "open"
    assert {c["status"] for c in body["children"]} == {"pending"}
    day2 = _advance(client, headers, sid, body["session"]["current_at"]).json()
    assert _orders(client, headers, sid)["bracket"]["status"] == "filled"
    assert day2["positions"][0]["quantity"] == "-10.000000"
    _advance(client, headers, sid, day2["current_at"])
    assert _orders(client, headers, sid)["take_profit"]["status"] == "filled"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"stop_price": "95", "target_price": "105"}, "stop must be above"),
        ({"side": "buy"}, "entry is a sell"),
    ],
)
def test_short_bracket_validation(session: Session, client: TestClient, extra, message) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = {"side": "sell", "order_type": "bracket", "quantity": "10", "entry_type": "market",
            "direction": "short", "stop_price": "105", "target_price": "95", **extra}  # fmt: skip
    response = client.post(f"/v1/replay/sessions/{sid}/orders", headers=headers, json=body)
    assert response.status_code == 400 and message in response.text


def test_short_bracket_refused_on_an_indian_listing(session: Session, client: TestClient) -> None:
    _daily(session, {D1: FLAT, D2: FLAT, D3: FLAT}, ticker="TCS.NS")
    headers = _headers(_user(session))
    sid = _create(client, headers, ticker="TCS.NS")["id"]
    response = _short(client, headers, sid)
    assert response.status_code == 400 and "US only" in response.text


def test_short_round_trip_reads_back(session: Session, client: TestClient) -> None:
    """Summary, forensics and the journal read a covered short."""
    _daily(session, {D1: FLAT, D2: ("100", "101", "94", "96"), D3: FLAT})
    headers = _headers(_user(session))
    sid = _create(client, headers)["id"]
    body = _short(client, headers, sid).json()
    open_short = client.get(f"/v1/replay/sessions/{sid}/summary", headers=headers).json()
    assert D(open_short["equity"]) == D("100000")  # cash + proceeds - the shares owed
    assert D(open_short["positions_market_value"]) == D("-1000")
    _advance(client, headers, sid, body["session"]["current_at"])
    after = client.get(f"/v1/replay/sessions/{sid}/summary", headers=headers).json()
    assert D(after["equity"]) == D("100050") and D(after["realized_pnl"]) == D("50")
    forensics = client.get(f"/v1/replay/sessions/{sid}/forensics", headers=headers)
    assert forensics.status_code == 200, forensics.text
    (episode,) = forensics.json()["episodes"]
    assert episode["side"] == "short" and episode["status"] == "closed"
    assert D(episode["weighted_entry_price"]) == D("100")
    assert D(episode["weighted_exit_price"]) == D("95")
    assert D(episode["realized_pnl"]) == D("50") and D(episode["return_pct"]) == D("5")
    journal = client.get("/v1/journal/entries", headers=headers)
    assert journal.status_code == 200, journal.text
    (entry,) = journal.json()["entries"]
    assert entry["side"] == "short" and entry["status"] == "closed"
    assert D(entry["net_pnl"]) == D("50")
