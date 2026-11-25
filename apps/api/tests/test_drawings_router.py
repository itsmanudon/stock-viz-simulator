"""A3.2: /v1/drawings, chart drawings anchored to bar dates and prices."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.models.drawing import MAX_DRAWINGS_PER_INSTRUMENT, Drawing
from stockviz.schemas import DrawingPoint
from stockviz.services.drawings import position_metrics
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
FIRST = date(2025, 3, 3)
LAST = date(2025, 4, 30)


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="T")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _seed(session: Session, ticker: str = "AAPL") -> None:
    seed_symbols(session, ticker)
    day = FIRST
    while day <= LAST:
        if day.weekday() < 5:
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime.combine(day, datetime.min.time()),
                    interval="1d",
                    open=Decimal(100),
                    high=Decimal(101),
                    low=Decimal(99),
                    close=Decimal(100),
                    volume=10,
                    source="yfinance",
                )
            )
        day += timedelta(days=1)
    session.commit()


def _post(client: TestClient, uid: int, **body):
    payload = {"ticker": "AAPL", **body}
    return client.post("/v1/drawings", json=payload, headers=_auth(uid))


def test_drawings_require_auth(client: TestClient) -> None:
    assert client.get("/v1/drawings?ticker=AAPL").status_code == 401
    assert client.post("/v1/drawings", json={}).status_code == 401
    assert client.patch("/v1/drawings/1", json={}).status_code == 401
    assert client.delete("/v1/drawings/1").status_code == 401


def test_crud_round_trip(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    empty = client.get("/v1/drawings?ticker=aapl", headers=_auth(uid)).json()
    assert empty == {
        "ticker": "AAPL",
        "drawings": [],
        "limit": MAX_DRAWINGS_PER_INSTRUMENT,
        "first_bar": "2025-03-03",
        "last_bar": "2025-04-30",
    }

    created = _post(
        client,
        uid,
        kind="trendline",
        points=[{"ts": "2025-03-10", "price": "100.5"}, {"ts": "2025-04-07", "price": "120"}],
        style={"colour": "violet", "width": 2, "dash": "dashed"},
        label="Support",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "trendline" and body["ticker"] == "AAPL"
    assert body["points"] == [
        {"ts": "2025-03-10", "price": "100.5"},
        {"ts": "2025-04-07", "price": "120"},
    ]
    assert body["style"] == {"colour": "violet", "width": 2, "dash": "dashed", "fill_opacity": 0.12}
    assert body["label"] == "Support" and body["locked"] is False and body["position"] is None

    did = body["id"]
    moved = client.patch(
        f"/v1/drawings/{did}",
        json={
            "points": [{"ts": "2025-03-11", "price": "101"}, {"ts": "2025-04-08", "price": "119"}]
        },
        headers=_auth(uid),
    )
    assert moved.status_code == 200
    assert moved.json()["points"][0] == {"ts": "2025-03-11", "price": "101"}
    assert moved.json()["label"] == "Support"
    cleared = client.patch(f"/v1/drawings/{did}", json={"label": None}, headers=_auth(uid))
    assert cleared.json()["label"] is None

    listed = client.get("/v1/drawings?ticker=AAPL", headers=_auth(uid)).json()["drawings"]
    assert [d["id"] for d in listed] == [did]

    assert client.delete(f"/v1/drawings/{did}", headers=_auth(uid)).status_code == 204
    assert client.get("/v1/drawings?ticker=AAPL", headers=_auth(uid)).json()["drawings"] == []


def test_unknown_symbol_is_404(session: Session, client: TestClient) -> None:
    uid = _user(session, "a@x.dev")
    assert client.get("/v1/drawings?ticker=NOPE", headers=_auth(uid)).status_code == 404
    assert (
        _post(client, uid, ticker="NOPE", kind="hline", points=[{"price": "1"}]).status_code == 404
    )


@pytest.mark.parametrize(
    ("kind", "points", "label", "message"),
    [
        ("trendline", [{"ts": "2025-03-10", "price": "1"}], None, "takes 2 points"),
        ("hline", [{"price": "1"}, {"price": "2"}], None, "takes 1 point"),
        ("channel", [{"ts": "2025-03-10", "price": "1"}] * 2, None, "takes 3 points"),
        ("trendline", [{"price": "1"}, {"ts": "2025-03-10", "price": "2"}], None, "needs a date"),
        (
            "ray",
            [{"ts": "2025-03-10", "price": "1"}, {"ts": "2025-05-01", "price": "2"}],
            None,
            "anchors must be between 2025-03-03 and 2025-04-30",
        ),
        (
            "rectangle",
            [{"ts": "2025-02-28", "price": "1"}, {"ts": "2025-03-10", "price": "2"}],
            None,
            "dated 2025-02-28",
        ),
        (
            "fib_retracement",
            [{"ts": "2025-03-10", "price": "5"}, {"ts": "2025-03-20", "price": "5"}],
            None,
            "must differ",
        ),
        ("text", [{"ts": "2025-03-10", "price": "5"}], "  ", "needs a label"),
        (
            "position_long",
            [{"ts": "2025-03-10", "price": "100"}, {"price": "105"}, {"price": "120"}],
            None,
            "stop < entry < target",
        ),
        (
            "position_short",
            [{"ts": "2025-03-10", "price": "100"}, {"price": "95"}, {"price": "90"}],
            None,
            "target < entry < stop",
        ),
        (
            "position_long",
            [
                {"ts": "2025-03-10", "price": "100"},
                {"ts": "2025-03-11", "price": "95"},
                {"price": "120"},
            ],
            None,
            "prices only",
        ),
        (
            "position_long",
            [{"price": "100"}, {"price": "95"}, {"price": "120"}],
            None,
            "needs a date",
        ),
    ],
)
def test_validation_per_kind(
    session: Session, client: TestClient, kind, points, label, message
) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    response = _post(client, uid, kind=kind, points=points, label=label)
    assert response.status_code == 422, response.text
    assert message in response.json()["detail"]


def test_schema_refuses_bad_prices_and_styles(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    assert _post(client, uid, kind="hline", points=[{"price": "0"}]).status_code == 422
    assert _post(client, uid, kind="hline", points=[{"price": "-3"}]).status_code == 422
    assert (
        _post(client, uid, kind="hline", points=[{"price": "1"}], style={"colour": "#ff0000"})
    ).status_code == 422
    assert (
        _post(client, uid, kind="hline", points=[{"price": "1"}], style={"width": 9})
    ).status_code == 422
    assert (
        _post(client, uid, kind="hline", points=[{"price": "1"}], label="x" * 81)
    ).status_code == 422
    assert _post(client, uid, kind="arrow", points=[{"price": "1"}]).status_code == 422


def test_every_kind_saves(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    a = {"ts": "2025-03-10", "price": "100"}
    b = {"ts": "2025-04-10", "price": "120"}
    c = {"ts": "2025-04-20", "price": "110"}
    cases = {
        "trendline": [a, b],
        "ray": [a, b],
        "hline": [{"price": "105"}],
        "rectangle": [a, b],
        "channel": [a, b, c],
        "fib_retracement": [a, b],
        "fib_extension": [a, b, c],
        "ruler": [a, b],
        "text": [a],
        "position_long": [a, {"price": "95"}, {"price": "115"}],
        "position_short": [a, {"price": "105"}, {"price": "85"}],
    }
    for kind, points in cases.items():
        response = _post(client, uid, kind=kind, points=points, label="note")
        assert response.status_code == 201, (kind, response.text)
    listed = client.get("/v1/drawings?ticker=AAPL", headers=_auth(uid)).json()["drawings"]
    assert [d["kind"] for d in listed] == list(cases)
    long = next(d for d in listed if d["kind"] == "position_long")["position"]
    assert long == {
        "side": "long",
        "entry": "100",
        "stop": "95",
        "target": "115",
        "risk_per_share": "5.000000",
        "reward_per_share": "15.000000",
        "reward_risk": "3.00",
        "stop_pct": "-5.00",
        "target_pct": "15.00",
    }


def test_position_metrics_short() -> None:
    points = [
        DrawingPoint(ts=date(2025, 3, 10), price=Decimal("200")),
        DrawingPoint(price=Decimal("210")),
        DrawingPoint(price=Decimal("175")),
    ]
    metrics = position_metrics("position_short", points)
    assert metrics is not None
    assert metrics.side == "short"
    assert metrics.risk_per_share == Decimal("10")
    assert metrics.reward_per_share == Decimal("25")
    assert metrics.reward_risk == Decimal("2.50")
    assert metrics.stop_pct == Decimal("5.00") and metrics.target_pct == Decimal("-12.50")
    assert position_metrics("hline", points[:1]) is None


def test_isolation_between_users(session: Session, client: TestClient) -> None:
    _seed(session)
    a = _user(session, "a@x.dev")
    b = _user(session, "b@x.dev")
    did = _post(client, a, kind="hline", points=[{"price": "101"}]).json()["id"]
    assert client.get("/v1/drawings?ticker=AAPL", headers=_auth(b)).json()["drawings"] == []
    assert (
        client.patch(f"/v1/drawings/{did}", json={"label": "x"}, headers=_auth(b)).status_code
        == 404
    )
    assert client.delete(f"/v1/drawings/{did}", headers=_auth(b)).status_code == 404
    assert len(client.get("/v1/drawings?ticker=AAPL", headers=_auth(a)).json()["drawings"]) == 1


def test_drawings_are_per_instrument(session: Session, client: TestClient) -> None:
    _seed(session, "AAPL")
    _seed(session, "MSFT")
    uid = _user(session, "a@x.dev")
    _post(client, uid, kind="hline", points=[{"price": "101"}])
    assert client.get("/v1/drawings?ticker=MSFT", headers=_auth(uid)).json()["drawings"] == []


def test_lock_blocks_edits_and_delete(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    did = _post(client, uid, kind="hline", points=[{"price": "101"}], locked=True).json()["id"]
    assert (
        client.patch(
            f"/v1/drawings/{did}", json={"points": [{"price": "102"}]}, headers=_auth(uid)
        ).status_code
        == 409
    )
    assert client.delete(f"/v1/drawings/{did}", headers=_auth(uid)).status_code == 409
    unlocked = client.patch(f"/v1/drawings/{did}", json={"locked": False}, headers=_auth(uid))
    assert unlocked.status_code == 200 and unlocked.json()["locked"] is False
    # Unlocking and moving in one request is allowed.
    client.patch(f"/v1/drawings/{did}", json={"locked": True}, headers=_auth(uid))
    both = client.patch(
        f"/v1/drawings/{did}",
        json={"locked": False, "points": [{"price": "103"}]},
        headers=_auth(uid),
    )
    assert both.status_code == 200 and both.json()["points"] == [{"ts": None, "price": "103"}]
    assert client.delete(f"/v1/drawings/{did}", headers=_auth(uid)).status_code == 204


def test_patch_revalidates(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    did = _post(
        client,
        uid,
        kind="position_long",
        points=[{"ts": "2025-03-10", "price": "100"}, {"price": "95"}, {"price": "115"}],
    ).json()["id"]
    bad = client.patch(
        f"/v1/drawings/{did}",
        json={"points": [{"ts": "2025-03-10", "price": "100"}, {"price": "105"}, {"price": "115"}]},
        headers=_auth(uid),
    )
    assert bad.status_code == 422
    text_id = _post(
        client, uid, kind="text", points=[{"ts": "2025-03-10", "price": "100"}], label="Gap"
    ).json()["id"]
    assert (
        client.patch(
            f"/v1/drawings/{text_id}", json={"label": None}, headers=_auth(uid)
        ).status_code
        == 422
    )


def test_no_bars_means_no_dated_anchor(session: Session, client: TestClient) -> None:
    seed_symbols(session, "AAPL")
    uid = _user(session, "a@x.dev")
    response = _post(client, uid, kind="trendline", points=[{"ts": "2025-03-10", "price": "1"}] * 2)
    assert response.status_code == 422 and "No stored bars" in response.json()["detail"]
    assert _post(client, uid, kind="hline", points=[{"price": "1"}]).status_code == 201


def test_limit_per_instrument(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session, "a@x.dev")
    first = _post(client, uid, kind="hline", points=[{"price": "1"}]).json()
    for _ in range(MAX_DRAWINGS_PER_INSTRUMENT - 1):
        session.add(
            Drawing(
                user_id=uid,
                instrument_id=session.get(Drawing, first["id"]).instrument_id,  # type: ignore[union-attr]
                kind="hline",
                points=[{"ts": None, "price": "1"}],
                style={},
            )
        )
    session.commit()
    over = _post(client, uid, kind="hline", points=[{"price": "1"}])
    assert over.status_code == 409 and "At most 200" in over.json()["detail"]
    # Another user is unaffected.
    other = _user(session, "b@x.dev")
    assert _post(client, other, kind="hline", points=[{"price": "1"}]).status_code == 201
