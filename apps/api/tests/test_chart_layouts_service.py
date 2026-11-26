"""A6.8 (M2.10): the chart template and layout services, below HTTP."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from stockviz.models import ChartLayout, Symbol, User
from stockviz.schemas import ChartPaneIn
from stockviz.services import chart_layouts, chart_templates


def _user(session: Session, email: str = "svc@stockviz.dev") -> int:
    user = User(email=email, name="Svc")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _status(fn, *args, **kwargs) -> int:
    with pytest.raises(HTTPException) as info:
        fn(*args, **kwargs)
    return info.value.status_code


def test_indicator_keys_follow_the_catalog_grammar() -> None:
    assert chart_templates.clean_indicators(["RSI_14", "rsi_14", "macd_8_21_5", "obv"]) == [
        "rsi_14",
        "macd_8_21_5",
        "obv",
    ]
    assert chart_templates.clean_indicators([]) == []
    for bad in ["rsi_", "rsi-14", "nope", "sma_0", "bb_20_2_9", ""]:
        assert _status(chart_templates.clean_indicators, [bad]) == 422, bad


def test_pane_heights_are_bounded() -> None:
    assert chart_templates.clean_pane_heights({"price": 48, "macd": 1200}) == {
        "price": 48,
        "macd": 1200,
    }
    assert _status(chart_templates.clean_pane_heights, {"price": 47}) == 422
    assert _status(chart_templates.clean_pane_heights, {"price": 1201}) == 422
    assert _status(chart_templates.clean_pane_heights, {"9lives": 100}) == 422
    many = {f"k{i}": 100 for i in range(17)}
    assert _status(chart_templates.clean_pane_heights, many) == 422


def test_names_are_collapsed_and_bounded() -> None:
    assert chart_templates.clean_name("  My   desk ") == "My desk"
    assert _status(chart_templates.clean_name, "   ") == 422
    assert _status(chart_templates.clean_name, "x" * 65) == 422


def test_linked_panes_share_a_symbol(session: Session) -> None:
    session.add(Symbol(ticker="AAA", name="A"))
    session.add(Symbol(ticker="BBB", name="B"))
    session.commit()
    uid = _user(session)
    panes = [
        ChartPaneIn(symbol="aaa", link="blue"),
        ChartPaneIn(symbol="AAA", interval="5m", link="blue"),
        ChartPaneIn(symbol="BBB", link="amber"),
        ChartPaneIn(symbol="BBB"),
    ]
    cleaned = chart_layouts.clean_panes(session, uid, "4", panes)
    assert [(p["symbol"], p["link"]) for p in cleaned] == [
        ("AAA", "blue"),
        ("AAA", "blue"),
        ("BBB", "amber"),
        ("BBB", None),
    ]
    clash = [ChartPaneIn(symbol="AAA", link="blue"), ChartPaneIn(symbol="BBB", link="blue")]
    assert _status(chart_layouts.clean_panes, session, uid, "2v", clash) == 422


def test_a_read_drops_a_template_the_user_no_longer_has(session: Session) -> None:
    session.add(Symbol(ticker="AAA", name="A"))
    session.commit()
    uid = _user(session)
    # A stale id written straight to the row (as after a lost delete).
    row = ChartLayout(
        user_id=uid,
        name="Old",
        grid="1",
        panes=[{"symbol": "AAA", "interval": "1d", "template_id": 4242, "link": None}],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    out = chart_layouts.layout_out(row, chart_templates.template_ids_of(session, uid))
    assert out.panes[0].template_id is None
    assert out.panes[0].symbol == "AAA"


def test_delete_template_touches_only_its_owners_layouts(session: Session) -> None:
    session.add(Symbol(ticker="AAA", name="A"))
    session.commit()
    me, them = _user(session, "me@x.dev"), _user(session, "them@x.dev")
    t = chart_templates.create_template(
        session, me, name="T", chart_type="candles", scale="linear", indicators=[], pane_heights={}
    )
    assert t.id is not None
    mine = chart_layouts.create_layout(
        session, me, name="M", grid="1", panes=[ChartPaneIn(symbol="AAA", template_id=t.id)]
    )
    # Their layout holds the same number in its JSON (written directly).
    theirs = ChartLayout(
        user_id=them,
        name="T",
        grid="1",
        panes=[{"symbol": "AAA", "interval": "1d", "template_id": t.id, "link": None}],
    )
    session.add(theirs)
    session.commit()
    chart_templates.delete_template(session, me, t.id)
    session.refresh(mine)
    session.refresh(theirs)
    assert mine.panes[0]["template_id"] is None
    assert theirs.panes[0]["template_id"] == t.id
