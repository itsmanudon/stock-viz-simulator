"""A6.8 (M2.10): `/v1/chart-templates` and `/v1/chart-layouts`.

HTTP-level, with real JWTs against the in-memory SQLite engine, like
``test_watchlists_router.py``. Synthetic symbols only.
"""

from __future__ import annotations

import typing

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import Symbol, User
from stockviz.models.chart_layout import (
    CHART_GRIDS,
    CHART_INTERVALS,
    CHART_SCALES,
    CHART_TYPES,
    LINK_COLOURS,
)
from stockviz.schemas import (
    ChartGridKey,
    ChartIntervalKey,
    ChartScaleKey,
    ChartTypeKey,
    LinkColourKey,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str = "charts@stockviz.dev") -> int:
    user = User(email=email, name="Charts")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbols(session: Session, *tickers: str) -> None:
    for t in tickers:
        session.add(Symbol(ticker=t, name=f"{t} Inc."))
    session.commit()


def _template(client: TestClient, h: dict[str, str], **body: object) -> dict:
    r = client.post(
        "/v1/chart-templates",
        json={"name": "Trend", "chart_type": "line", "scale": "log", **body},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pane(symbol: str, interval: str = "1d", template_id=None, link=None) -> dict:
    return {"symbol": symbol, "interval": interval, "template_id": template_id, "link": link}


def test_literals_match_the_model_tuples() -> None:
    assert typing.get_args(ChartTypeKey) == CHART_TYPES
    assert typing.get_args(ChartScaleKey) == CHART_SCALES
    assert typing.get_args(ChartIntervalKey) == CHART_INTERVALS
    assert typing.get_args(ChartGridKey) == CHART_GRIDS
    assert typing.get_args(LinkColourKey) == LINK_COLOURS
    assert len(LINK_COLOURS) == 7


def test_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/chart-templates").status_code == 401
    assert client.post("/v1/chart-templates", json={"name": "x"}).status_code == 401
    assert client.get("/v1/chart-layouts").status_code == 401
    assert client.get("/v1/chart-layouts/1").status_code == 401


def test_template_crud_and_validation(session: Session, client: TestClient) -> None:
    h = _headers(_user(session))
    assert client.get("/v1/chart-templates", headers=h).json() == []
    t = _template(
        client,
        h,
        indicators=["SMA_50", "bb_20_2", "macd", "sma_50"],
        pane_heights={"price": 320, "rsi": 90},
    )
    # Lower-cased, each once, in order.
    assert t["indicators"] == ["sma_50", "bb_20_2", "macd"]
    assert t["pane_heights"] == {"price": 320, "rsi": 90}
    assert (t["chart_type"], t["scale"]) == ("line", "log")

    def post(**body: object) -> int:
        return client.post(
            "/v1/chart-templates", json={"name": "Bad", **body}, headers=h
        ).status_code

    assert post(indicators=["nope_3"]) == 422  # not in the registry
    assert post(indicators=["rsi_14_2_9"]) == 422  # too many parameters
    assert post(indicators=["rsi_0"]) == 422  # out of the parameter's bounds
    assert post(indicators=["rsi_1e3"]) == 422  # not the grammar
    assert post(chart_type="renko") == 422
    assert post(scale="sqrt") == 422
    assert post(pane_heights={"price": 10}) == 422
    assert post(pane_heights={"Price!": 100}) == 422
    assert post(indicators=[f"sma_{n}" for n in range(1, 18)]) == 422
    assert post(name="trend") == 409  # the name, ignoring case

    r = client.patch(
        f"/v1/chart-templates/{t['id']}", json={"scale": "percent", "indicators": []}, headers=h
    )
    assert r.status_code == 200
    assert (r.json()["scale"], r.json()["indicators"], r.json()["name"]) == (
        "percent",
        [],
        "Trend",
    )
    assert (
        client.patch(
            f"/v1/chart-templates/{t['id']}", json={"indicators": ["bogus"]}, headers=h
        ).status_code
        == 422
    )
    assert client.delete(f"/v1/chart-templates/{t['id']}", headers=h).status_code == 204
    assert client.get("/v1/chart-templates", headers=h).json() == []


def test_template_cap(session: Session, client: TestClient, monkeypatch) -> None:
    from stockviz.services import chart_templates

    monkeypatch.setattr(chart_templates, "MAX_TEMPLATES_PER_USER", 2)
    h = _headers(_user(session))
    _template(client, h, name="One")
    _template(client, h, name="Two")
    r = client.post("/v1/chart-templates", json={"name": "Three"}, headers=h)
    assert r.status_code == 409 and "At most 2" in r.json()["detail"]


def test_four_pane_layout_round_trips(session: Session, client: TestClient) -> None:
    """Acceptance: a saved four-pane layout reloads with each pane's symbol,
    interval and template (and link colour)."""
    _symbols(session, "AAA", "BBB", "CCC")
    h = _headers(_user(session))
    trend = _template(client, h, name="Trend", indicators=["sma_20"])
    osc = _template(client, h, name="Oscillators", indicators=["rsi_14", "macd"])
    panes = [
        _pane("aaa", "1wk", trend["id"], "blue"),
        _pane("AAA", "15m", osc["id"], "blue"),
        _pane("BBB", "1d", None, "pink"),
        _pane("CCC", "60m", trend["id"], None),
    ]
    r = client.post("/v1/chart-layouts", json={"name": "Desk", "grid": "4", "panes": panes},
                    headers=h)  # fmt: skip
    assert r.status_code == 201, r.text
    layout_id = r.json()["id"]

    loaded = client.get(f"/v1/chart-layouts/{layout_id}", headers=h).json()
    assert loaded["grid"] == "4" and loaded["name"] == "Desk"
    assert [(p["symbol"], p["interval"], p["template_id"], p["link"]) for p in loaded["panes"]] == [
        ("AAA", "1wk", trend["id"], "blue"),
        ("AAA", "15m", osc["id"], "blue"),
        ("BBB", "1d", None, "pink"),
        ("CCC", "60m", trend["id"], None),
    ]
    assert [lay["id"] for lay in client.get("/v1/chart-layouts", headers=h).json()] == [layout_id]

    # Deleting a template clears it from the layout; the rest is kept.
    assert client.delete(f"/v1/chart-templates/{trend['id']}", headers=h).status_code == 204
    after = client.get(f"/v1/chart-layouts/{layout_id}", headers=h).json()
    assert [p["template_id"] for p in after["panes"]] == [None, osc["id"], None, None]
    assert [p["symbol"] for p in after["panes"]] == ["AAA", "AAA", "BBB", "CCC"]


def test_layout_validation(session: Session, client: TestClient) -> None:
    _symbols(session, "AAA", "BBB")
    h = _headers(_user(session))

    def post(grid: str, panes: list[dict], name: str = "L") -> int:
        return client.post(
            "/v1/chart-layouts", json={"name": name, "grid": grid, "panes": panes}, headers=h
        ).status_code

    assert post("4", [_pane("AAA")]) == 422  # a 4 grid has four panes
    assert post("2v", [_pane("AAA")] * 3) == 422
    assert post("1", [_pane("ZZZ")]) == 422  # unknown symbol
    assert post("1", [_pane("AAA", "2h")]) == 422  # unknown interval
    assert post("1", [_pane("AAA", link="teal")]) == 422  # not a link colour
    assert post("3", [_pane("AAA")] * 3) == 422  # not a grid
    assert post("1", [_pane("AAA", template_id=999)]) == 422  # not your template
    # One symbol per link colour.
    assert post("2h", [_pane("AAA", link="blue"), _pane("BBB", link="blue")]) == 422
    assert post("2h", [_pane("AAA", link="blue"), _pane("BBB", link="lime")]) == 201
    assert post("1", [_pane("AAA")], name="l") == 409  # the name, ignoring case


def test_layout_patch_and_delete(session: Session, client: TestClient) -> None:
    _symbols(session, "AAA", "BBB")
    h = _headers(_user(session))
    lay = client.post(
        "/v1/chart-layouts", json={"name": "One", "panes": [_pane("AAA")]}, headers=h
    ).json()
    assert lay["grid"] == "1"
    lid = lay["id"]
    # A grid change needs its panes.
    assert (
        client.patch(f"/v1/chart-layouts/{lid}", json={"grid": "2v"}, headers=h).status_code == 422
    )
    r = client.patch(
        f"/v1/chart-layouts/{lid}",
        json={"name": "Two", "grid": "2v", "panes": [_pane("AAA"), _pane("BBB", "1mo")]},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["grid"], len(r.json()["panes"])) == ("Two", "2v", 2)
    # Panes alone keep the grid.
    r = client.patch(
        f"/v1/chart-layouts/{lid}", json={"panes": [_pane("BBB"), _pane("AAA")]}, headers=h
    )
    assert [p["symbol"] for p in r.json()["panes"]] == ["BBB", "AAA"]
    assert client.delete(f"/v1/chart-layouts/{lid}", headers=h).status_code == 204
    assert client.get(f"/v1/chart-layouts/{lid}", headers=h).status_code == 404


def test_each_user_sees_only_their_own(session: Session, client: TestClient) -> None:
    _symbols(session, "AAA")
    mine = _headers(_user(session, "me@stockviz.dev"))
    theirs = _headers(_user(session, "them@stockviz.dev"))
    t = _template(client, mine)
    lay = client.post(
        "/v1/chart-layouts",
        json={"name": "Mine", "panes": [_pane("AAA", template_id=t["id"])]},
        headers=mine,
    ).json()

    assert client.get("/v1/chart-templates", headers=theirs).json() == []
    assert client.get("/v1/chart-layouts", headers=theirs).json() == []
    assert client.get(f"/v1/chart-layouts/{lay['id']}", headers=theirs).status_code == 404
    assert (
        client.patch(f"/v1/chart-layouts/{lay['id']}", json={"name": "X"}, headers=theirs)
    ).status_code == 404
    assert client.delete(f"/v1/chart-layouts/{lay['id']}", headers=theirs).status_code == 404
    assert (
        client.patch(f"/v1/chart-templates/{t['id']}", json={"name": "X"}, headers=theirs)
    ).status_code == 404
    assert client.delete(f"/v1/chart-templates/{t['id']}", headers=theirs).status_code == 404
    # Another user's template can't be put in a layout.
    r = client.post(
        "/v1/chart-layouts",
        json={"name": "Theirs", "panes": [_pane("AAA", template_id=t["id"])]},
        headers=theirs,
    )
    assert r.status_code == 422
    # Their own names don't collide with mine.
    assert _template(client, theirs)["name"] == "Trend"
