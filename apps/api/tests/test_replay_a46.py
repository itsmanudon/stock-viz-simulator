"""A4.6 (M9.1, M9.2): replay in any currency, the 30-day lag, indicators and
news cut at the clock, session-only drawings, resting limit and stop orders,
fees in replay.

The design note's acceptance (section 3): an INR replay on an NSE symbol
trades in rupees and refuses an end date inside 30 days; news and indicators
never show values after ``current_at`` (``test_acceptance_*``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import (
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    Drawing,
    PriceBar,
    ReplayFill,
    ReplayOrder,
    Symbol,
    User,
)
from stockviz.services.fee_view import default_schedule_name
from stockviz.services.instruments import instrument_ids
from stockviz.services.replay import (
    ReplayLagError,
    ReplayNotTradable,
    advance_replay_session,
    cancel_replay_session,
    compute_replay_forensics,
    compute_replay_summary,
    create_replay_session,
    submit_replay_order,
)
from stockviz.services.simulation import OrderSide, SimulationOrderType, get_fee_schedule
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token
START = datetime(2025, 3, 3)


def _auth(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str = "a46@stockviz.dev") -> int:
    row = User(email=email, name="A46")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def _days(n: int, start: datetime = START) -> list[datetime]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _seed(
    session: Session,
    ticker: str,
    closes: list[Decimal],
    *,
    currency: str,
    start: datetime = START,
) -> list[datetime]:
    if session.get(Symbol, ticker) is None:
        session.add(Symbol(ticker=ticker, name=ticker, currency=currency))
        session.commit()
    days = _days(len(closes), start)
    for ts, close in zip(days, closes, strict=True):
        session.add(
            PriceBar(
                ticker=ticker,
                ts=ts,
                interval="1d",
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=100_000,
                source="test",
            )
        )
    session.commit()
    return days


def _walk(n: int, base: float = 100.0) -> list[Decimal]:
    """A deterministic zig-zag so indicators move."""
    return [Decimal(str(round(base + (i % 7) * 1.5 - (i % 3) * 2 + i * 0.1, 2))) for i in range(n)]


def _settings(monkeypatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    get_settings.cache_clear()


# --- currencies, cash, fees ---------------------------------------------------


def test_acceptance_inr_replay_trades_in_rupees_and_refuses_recent_end(session: Session) -> None:
    days = _seed(session, "TCS.NS", _walk(10, 3500), currency="INR")
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="TCS.NS", start_at=days[0], end_at=days[-1]
    )
    assert replay.currency == "INR"
    assert replay.starting_cash == Decimal("1000000.00")  # ₹10 lakh
    assert replay.fee_schedule == default_schedule_name("TCS.NS") == "in_equity_delivery_nse"
    result = submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal(10),
    )
    fill = result.fill
    assert fill is not None and fill.fees > 0
    expected = get_fee_schedule("in_equity_delivery_nse").fees(
        OrderSide.BUY, Decimal(10), fill.fill_price, on=days[0].date()
    )
    assert fill.fees == expected.total
    assert result.replay.cash_balance == Decimal("1000000") - fill.fill_price * 10 - fill.fees
    assert fill.fee_lines and {line["key"] for line in fill.fee_lines} >= {"stt", "stamp_duty"}
    summary = compute_replay_summary(session, result.replay)
    assert summary.fees_paid == fill.fees

    # The same symbol, ending inside 30 days of "today", is refused.
    with pytest.raises(ReplayLagError, match="at least 30 days"):
        create_replay_session(
            session,
            user_id=uid,
            ticker="TCS.NS",
            start_at=days[0],
            end_at=days[-1],
            today=days[-1].date() + timedelta(days=10),
        )
    # Exactly 30 days after the end is allowed.
    ok = create_replay_session(
        session,
        user_id=uid,
        ticker="TCS.NS",
        start_at=days[0],
        end_at=days[-1],
        today=days[-1].date() + timedelta(days=30),
    )
    assert ok.lag_override is False


def test_lag_applies_to_bse_not_us(session: Session) -> None:
    days = _seed(session, "RELIANCE.BO", _walk(5, 2500), currency="INR")
    _seed(session, "AAPL", _walk(5), currency="USD")
    uid = _user(session)
    today = days[-1].date() + timedelta(days=1)
    with pytest.raises(ReplayLagError):
        create_replay_session(
            session,
            user_id=uid,
            ticker="RELIANCE.BO",
            start_at=days[0],
            end_at=days[-1],
            today=today,
        )
    us = create_replay_session(
        session, user_id=uid, ticker="AAPL", start_at=days[0], end_at=days[-1], today=today
    )
    assert us.currency == "USD" and us.starting_cash == Decimal("100000.00")
    assert us.fee_schedule == "none"


def test_lag_override_is_owner_only_and_setting_can_turn_it_off(
    session: Session, monkeypatch
) -> None:
    days = _seed(session, "TCS.NS", _walk(5, 3500), currency="INR")
    owner, other = _user(session, "owner@x.dev"), _user(session, "other@x.dev")
    today = days[-1].date() + timedelta(days=2)
    _settings(monkeypatch, REPLAY_LAG_OVERRIDE_USER_IDS=str(owner))
    waived = create_replay_session(
        session, user_id=owner, ticker="TCS.NS", start_at=days[0], end_at=days[-1], today=today
    )
    assert waived.lag_override is True
    with pytest.raises(ReplayLagError):
        create_replay_session(
            session, user_id=other, ticker="TCS.NS", start_at=days[0], end_at=days[-1], today=today
        )
    _settings(monkeypatch, REPLAY_LAG_OVERRIDE_USER_IDS="", REPLAY_MIN_LAG_DAYS="0")
    free = create_replay_session(
        session, user_id=other, ticker="TCS.NS", start_at=days[0], end_at=days[-1], today=today
    )
    assert free.lag_override is False


def test_default_override_is_empty() -> None:
    get_settings.cache_clear()
    assert get_settings().replay_lag_override_user_ids == []
    assert get_settings().replay_min_lag_days == 30


def test_http_create_refusal_message_and_availability(session: Session, client: TestClient) -> None:
    # Bars dated in the last few days: the session would end inside the lag.
    today = date.today()
    start = datetime.combine(today - timedelta(days=12), datetime.min.time())
    days = _seed(session, "INFY.NS", _walk(6, 1500), currency="INR", start=start)
    uid = _user(session)
    response = client.post(
        "/v1/replay/sessions",
        headers=_auth(uid),
        json={"ticker": "INFY.NS", "start_at": days[0].isoformat(), "end_at": days[-1].isoformat()},
    )
    assert response.status_code == 400
    assert "at least 30 days before today" in response.json()["detail"]
    available = client.get("/v1/replay/availability?ticker=INFY.NS", headers=_auth(uid)).json()
    assert available["currency"] == "INR"
    assert available["lag_days"] == 30
    assert available["default_starting_cash"] == "1000000.00"
    assert available["fee_schedule"] == "in_equity_delivery_nse"
    assert date.fromisoformat(available["max_end"]) <= today - timedelta(days=30)
    # A request field cannot relax the lag.
    sneaky = client.post(
        "/v1/replay/sessions",
        headers=_auth(uid),
        json={
            "ticker": "INFY.NS",
            "start_at": days[0].isoformat(),
            "end_at": days[-1].isoformat(),
            "lag_override": True,
        },
    )
    assert sneaky.status_code == 422


def test_index_session_watches_but_does_not_trade(session: Session) -> None:
    days = _seed(session, "^NSEI", _walk(5, 22000), currency="INR")
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="^NSEI", start_at=days[0], end_at=days[-1]
    )
    advance_replay_session(session, replay=replay)
    with pytest.raises(ReplayNotTradable):
        submit_replay_order(
            session,
            replay=replay,
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal(1),
        )
    with pytest.raises(ReplayNotTradable):
        submit_replay_order(
            session,
            replay=replay,
            side=OrderSide.BUY,
            order_type=SimulationOrderType.LIMIT,
            quantity=Decimal(1),
            limit_price=Decimal(1),
        )


# --- resting orders -----------------------------------------------------------


def _usd_session(session: Session, closes: list[str]):
    days = _seed(session, "AAPL", [Decimal(c) for c in closes], currency="USD")
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="AAPL", start_at=days[0], end_at=days[-1]
    )
    return replay, days, uid


def _place(session, replay, side, kind, qty, price):
    return submit_replay_order(
        session,
        replay=replay,
        side=side,
        order_type=kind,
        quantity=Decimal(qty),
        limit_price=Decimal(price),
    )


def test_limit_buy_rests_across_steps_then_fills_at_the_close(session: Session) -> None:
    replay, days, _ = _usd_session(session, ["100", "99", "97", "94", "96"])
    placed = _place(session, replay, OrderSide.BUY, SimulationOrderType.LIMIT, 10, "95")
    order = placed.order
    assert order is not None and order.placed_at == days[0]
    # 99 and 97: above the limit, still open.
    for _ in range(2):
        replay = advance_replay_session(session, replay=replay)
        session.refresh(order)
        assert order.status == "open"
    replay = advance_replay_session(session, replay=replay)  # close 94 <= 95
    session.refresh(order)
    assert order.status == "filled" and order.resolved_at == days[3]
    fill = session.exec(select(ReplayFill).where(ReplayFill.order_id == order.id)).one()
    assert fill.fill_price == Decimal("94") and fill.order_type == "limit"
    assert replay.cash_balance == Decimal("100000") - Decimal("940")


def test_limit_placed_on_a_bar_is_not_judged_on_that_bar(session: Session) -> None:
    replay, _, _ = _usd_session(session, ["100", "120", "80"])
    placed = _place(session, replay, OrderSide.BUY, SimulationOrderType.LIMIT, 1, "150")
    assert placed.fill is None and placed.order is not None and placed.order.status == "open"
    assert session.exec(select(ReplayFill)).first() is None
    advance_replay_session(session, replay=replay)
    session.refresh(placed.order)
    assert placed.order.status == "filled"


def test_stop_loss_and_take_profit_fill_and_the_other_is_rejected(session: Session) -> None:
    replay, _, _ = _usd_session(session, ["100", "100", "90", "120"])
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal(10),
    )
    stop = _place(session, replay, OrderSide.SELL, SimulationOrderType.STOP_LOSS, 10, "95").order
    target = _place(
        session, replay, OrderSide.SELL, SimulationOrderType.TAKE_PROFIT, 10, "115"
    ).order
    assert stop is not None and target is not None
    replay = advance_replay_session(session, replay=replay)  # 100: neither
    replay = advance_replay_session(session, replay=replay)  # 90: the stop
    session.refresh(stop)
    session.refresh(target)
    assert stop.status == "filled" and target.status == "open"
    replay = advance_replay_session(session, replay=replay)  # 120: target, but no shares left
    session.refresh(target)
    assert target.status == "rejected" and "position" in (target.reason or "")
    assert replay.cash_balance == Decimal("100000") - Decimal("1000") + Decimal("900")


def test_buy_side_stop_is_refused_and_cancel_works(session: Session, client: TestClient) -> None:
    replay, _, uid = _usd_session(session, ["100", "101", "102"])
    headers = _auth(uid)
    bad = client.post(
        f"/v1/replay/sessions/{replay.id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "stop_loss", "quantity": "1", "limit_price": "90"},
    )
    assert bad.status_code == 400 and "sell-only" in bad.json()["detail"]
    placed = client.post(
        f"/v1/replay/sessions/{replay.id}/orders",
        headers=headers,
        json={"side": "buy", "order_type": "limit", "quantity": "2", "limit_price": "50"},
    )
    assert placed.status_code == 200
    body = placed.json()
    assert body["decision"] is None and body["order"]["status"] == "open"
    assert body["session"]["open_orders"] == 1
    order_id = body["order"]["id"]
    listed = client.get(f"/v1/replay/sessions/{replay.id}/orders", headers=headers).json()
    assert [o["id"] for o in listed] == [order_id]
    cancelled = client.post(
        f"/v1/replay/sessions/{replay.id}/orders/{order_id}/cancel", headers=headers
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = client.post(
        f"/v1/replay/sessions/{replay.id}/orders/{order_id}/cancel", headers=headers
    )
    assert again.status_code == 409
    other = _user(session, "intruder@x.dev")
    assert (
        client.get(f"/v1/replay/sessions/{replay.id}/orders", headers=_auth(other)).status_code
        == 404
    )


def test_open_orders_expire_on_completion_and_cancel_with_the_session(session: Session) -> None:
    replay, _, _ = _usd_session(session, ["100", "101"])
    order = _place(session, replay, OrderSide.BUY, SimulationOrderType.LIMIT, 1, "50").order
    replay = advance_replay_session(session, replay=replay)
    replay = advance_replay_session(session, replay=replay)  # from the last bar: completed
    assert replay.status == "completed"
    session.refresh(order)
    assert order is not None and order.status == "expired"

    replay2, _d, _ = _usd_session_more(session)
    order2 = _place(session, replay2, OrderSide.BUY, SimulationOrderType.LIMIT, 1, "50").order
    cancel_replay_session(session, replay=replay2)
    session.refresh(order2)
    assert order2 is not None and order2.status == "cancelled"


def _usd_session_more(session: Session):
    days = _seed(session, "MSFT", [Decimal("10"), Decimal("11"), Decimal("12")], currency="USD")
    uid = _user(session, "more@x.dev")
    return (
        create_replay_session(
            session, user_id=uid, ticker="MSFT", start_at=days[0], end_at=days[-1]
        ),
        days,
        uid,
    )


def test_resting_inr_order_pays_fees_and_dp_once_per_day(session: Session) -> None:
    days = _seed(session, "TCS.NS", [Decimal(c) for c in ("3500", "3500", "3400")], currency="INR")
    uid = _user(session)
    replay = create_replay_session(
        session, user_id=uid, ticker="TCS.NS", start_at=days[0], end_at=days[-1]
    )
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal(20),
    )
    a = _place(session, replay, OrderSide.SELL, SimulationOrderType.STOP_LOSS, 10, "3450").order
    b = _place(session, replay, OrderSide.SELL, SimulationOrderType.STOP_LOSS, 10, "3450").order
    advance_replay_session(session, replay=replay)
    replay = advance_replay_session(session, replay=replay)
    fills = session.exec(
        select(ReplayFill).where(ReplayFill.side == "sell").order_by(ReplayFill.id)  # type: ignore[arg-type]
    ).all()
    assert [f.order_id for f in fills] == [a.id, b.id]  # type: ignore[union-attr]
    schedule = get_fee_schedule("in_equity_delivery_nse")
    first = schedule.fees(OrderSide.SELL, Decimal(10), Decimal(3400), on=days[2].date())
    second = schedule.fees(
        OrderSide.SELL, Decimal(10), Decimal(3400), on=days[2].date(), dp_due=False
    )
    assert (fills[0].fees, fills[1].fees) == (first.total, second.total)
    assert first.total > second.total  # the DP charge, once that day
    forensics = compute_replay_forensics(session, replay)
    summary = compute_replay_summary(session, replay)
    assert forensics.equity == summary.equity
    episode = forensics.episodes[0]
    fees = sum((f.fees for f in session.exec(select(ReplayFill)).all()), Decimal(0))
    assert episode.fees == fees
    assert episode.realized_pnl == (Decimal(3400) - Decimal(3500)) * 20 - fees


# --- indicators and news never after the clock --------------------------------


def _doc(session: Session, doc_id: str, ticker: str, at: datetime) -> None:
    entity = f"ent_{ticker}"
    if session.get(AegisMapping, f"map_{ticker}") is None:
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}",
                entity_id=entity,
                scheme="provider_id",
                identifier=f"stockviz:{ticker}",
                created_at=datetime(2024, 1, 1),
            )
        )
    session.add(
        AegisDocument(
            document_id=doc_id,
            source_id="src",
            source_name="Wire",
            title=f"Headline {doc_id}",
            url=f"https://n.test/{doc_id}",
            first_seen_at=at,
            available_at=at,
            last_signed_at=at,
        )
    )
    session.flush()
    session.add(
        AegisDocumentEntity(
            document_id=doc_id,
            entity_id=entity,
            canonical_name=entity,
            kind="organization",
            resolution_analysis_id=f"r_{doc_id}",
            confidence=1.0,
        )
    )
    session.commit()


def test_acceptance_indicators_and_news_never_after_the_clock(
    session: Session, client: TestClient
) -> None:
    closes = _walk(80, 3000)
    days = _seed(session, "TCS.NS", closes, currency="INR")
    # Future bars beyond the session's end, wildly different: they must change nothing.
    future = _seed(
        session,
        "TCS.NS",
        [Decimal("99999")] * 5,
        currency="INR",
        start=days[-1] + timedelta(days=1),
    )
    assert future[0] > days[-1]
    # News: one before the start, one inside the range (mid-session), one after the end.
    _doc(session, "early", "TCS.NS", days[40] - timedelta(hours=3))
    _doc(session, "mid", "TCS.NS", days[45] + timedelta(hours=10))
    _doc(session, "late", "TCS.NS", future[1] + timedelta(hours=1))
    uid = _user(session)
    headers = _auth(uid)
    created = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "TCS.NS", "start_at": days[40].isoformat(), "end_at": days[-1].isoformat()},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    names = "sma_20,rsi_14,macd,bb_20_2"
    for step in range(10):
        state = client.get(f"/v1/replay/sessions/{sid}", headers=headers).json()
        clock = datetime.fromisoformat(state["current_at"].replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        bundle = client.get(
            f"/v1/replay/sessions/{sid}/indicators?names={names}", headers=headers
        ).json()
        stamps = [p["ts"] for pts in bundle["series"].values() for p in pts]
        stamps += [p["ts"] for p in bundle["macd"] or []]
        assert stamps, step
        assert (
            max(
                datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)
                for t in stamps
            )
            <= clock
        )
        # The same values the live route gives with its window cut at the clock.
        live = client.get(
            f"/v1/symbols/TCS.NS/indicators?names={names}&from={days[40].isoformat()}"
            f"&to={clock.isoformat()}&limit=5000"
        ).json()
        assert bundle["series"] == live["series"] and bundle["macd"] == live["macd"], step
        events = client.get(f"/v1/replay/sessions/{sid}/events", headers=headers).json()
        ids = [h["id"] for e in events["events"] if e["type"] == "news" for h in e["headlines"]]
        available = [
            h["available_at"]
            for e in events["events"]
            if e["type"] == "news"
            for h in e["headlines"]
        ]
        assert all(
            datetime.fromisoformat(a.replace("Z", "+00:00")).replace(tzinfo=None) <= clock
            for a in available
        )
        assert "late" not in ids and "early" not in ids  # before start_at's date
        assert ("mid" in ids) == (clock > days[45] + timedelta(hours=10)), step
        client.post(f"/v1/replay/sessions/{sid}/advance", headers=headers)


def test_events_include_the_sessions_fills_only(session: Session, client: TestClient) -> None:
    replay, _, uid = _usd_session(session, ["100", "101", "102"])
    other, _d, _u = _usd_session_more(session)
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal(1),
    )
    submit_replay_order(
        session,
        replay=other,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal(1),
    )
    events = client.get(f"/v1/replay/sessions/{replay.id}/events", headers=_auth(uid)).json()
    fills = [e for e in events["events"] if e["type"] == "fill"]
    assert len(fills) == 1 and fills[0]["price"] == "100.000000"


# --- session drawings -----------------------------------------------------------


def test_session_drawings_are_isolated(session: Session, client: TestClient) -> None:
    days = _seed(session, "AAPL", _walk(6), currency="USD")
    uid = _user(session)
    headers = _auth(uid)
    first = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": days[0].isoformat(), "end_at": days[-1].isoformat()},
    ).json()
    second = client.post(
        "/v1/replay/sessions",
        headers=headers,
        json={"ticker": "AAPL", "start_at": days[0].isoformat(), "end_at": days[-1].isoformat()},
    ).json()
    # A live drawing on a date after the session clock.
    live = client.post(
        "/v1/drawings",
        headers=headers,
        json={"ticker": "AAPL", "kind": "hline", "points": [{"ts": None, "price": "123"}]},
    )
    assert live.status_code == 201
    base = f"/v1/replay/sessions/{first['id']}/drawings"
    line = {
        "kind": "trendline",
        "points": [
            {"ts": days[0].date().isoformat(), "price": "100"},
            {"ts": days[0].date().isoformat(), "price": "101"},
        ],
    }
    made = client.post(base, headers=headers, json=line)
    assert made.status_code == 201, made.text
    listed = client.get(base, headers=headers).json()
    assert [d["id"] for d in listed["drawings"]] == [made.json()["id"]]
    assert listed["first_bar"] == listed["last_bar"] == days[0].date().isoformat()
    # The live chart and the other session see none of it; the session sees no live one.
    live_list = client.get("/v1/drawings?ticker=AAPL", headers=headers).json()["drawings"]
    assert [d["id"] for d in live_list] == [live.json()["id"]]
    assert (
        client.get(f"/v1/replay/sessions/{second['id']}/drawings", headers=headers).json()[
            "drawings"
        ]
        == []
    )
    assert session.exec(select(Drawing)).all().__len__() == 1
    # Anchored after the clock: refused. An anchored VWAP: refused.
    later = {"kind": "hline", "points": [{"ts": days[2].date().isoformat(), "price": "100"}]}
    assert client.post(base, headers=headers, json=later).status_code == 422
    avwap = {"kind": "avwap", "label": "x", "points": [{"ts": days[0].date().isoformat()}]}
    assert client.post(base, headers=headers, json=avwap).status_code == 422
    # After advancing, the clock allows the later anchor.
    client.post(f"/v1/replay/sessions/{first['id']}/advance", headers=headers)
    client.post(f"/v1/replay/sessions/{first['id']}/advance", headers=headers)
    assert client.post(base, headers=headers, json=later).status_code == 201
    drawing_id = made.json()["id"]
    patched = client.patch(f"{base}/{drawing_id}", headers=headers, json={"label": "trend"})
    assert patched.status_code == 200 and patched.json()["label"] == "trend"
    # Another user, or another session's path, cannot reach it.
    other = _user(session, "other-a46@x.dev")
    assert client.get(base, headers=_auth(other)).status_code == 404
    wrong = f"/v1/replay/sessions/{second['id']}/drawings/{drawing_id}"
    assert client.delete(wrong, headers=headers).status_code == 404
    assert client.delete(f"{base}/{drawing_id}", headers=headers).status_code == 204


def test_no_prize_or_leaderboard_in_replay() -> None:
    """The design note: no prize or leaderboard anywhere in replay."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stockviz"
    text = "\n".join(
        p.read_text()
        for p in [*(root / "services" / "replay").glob("*.py"), root / "routers" / "replay.py"]
    ).lower()
    for word in ("leaderboard", "prize", "reward pool", "rank among"):
        lines = [ln for ln in text.splitlines() if word in ln and "no prize" not in ln]
        assert not lines, (word, lines)


def test_replay_order_rows_need_a_session(session: Session) -> None:
    replay, _, _ = _usd_session(session, ["1", "2"])
    _place(session, replay, OrderSide.BUY, SimulationOrderType.LIMIT, 1, "1")
    rows = session.exec(select(ReplayOrder)).all()
    assert len(rows) == 1 and rows[0].session_id == replay.id
    assert instrument_ids(session, ["AAPL"])  # the symbol's instrument exists
