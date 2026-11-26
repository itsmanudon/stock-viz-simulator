"""A3.3 (M2.5): the Rule DSL's ``drawing("label")`` and ``avwap("label")``.

Parse, type and canonical form; values per drawing kind; user scoping (only
the owner resolves them, presets and forks refuse them, the screener needs a
signed-in caller); a deleted or renamed drawing is unknown and its alert
stays quiet; ``rule-check --user-id``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import Alert, AlertEvent, AlertKind, PriceBar, Setup, User
from stockviz.models.drawing import Drawing
from stockviz.services import avwap as avwap_math
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.dsl import RuleError, compile_rule, evaluate_at, load_symbol, parse, point
from stockviz.services.dsl import vector as vector_of
from stockviz.services.dsl.data import SymbolData, bars_frame
from stockviz.services.dsl.drawings import DrawingRef, Drawings
from stockviz.services.dsl.printer import to_text
from stockviz.services.instruments import instrument_ids
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.setups import store
from stockviz.services.setups.presets import Preset, seed_setups
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


# --- parse, type, canonical --------------------------------------------------


def test_parse_print_round_trip() -> None:
    for text in (
        'close > drawing("Support").price',
        'drawing("zone").top[1] < close',
        'close crosses_above avwap("swing")',
        'avwap("swing").upper2 > close',
    ):
        tree = parse(text)
        assert parse(to_text(tree)) == tree
        assert to_text(tree) == text


def test_canonical_form_lowercases_labels_and_drops_the_default_output() -> None:
    a = compile_rule('close > drawing("  My   Support ").price')
    b = compile_rule('close > drawing("my support").price')
    assert a.canonical_text == 'close > drawing("my support").price' and a.hash == b.hash
    c = compile_rule('close > avwap("Swing").vwap')
    assert c.canonical_text == 'close > avwap("swing")'
    assert c.hash == compile_rule('close > avwap("swing")').hash


def test_types_and_scoping_flags() -> None:
    rule = compile_rule('close > drawing("s").price and close > sma(close, 20)')
    assert rule.user_scoped and rule.needs.drawings and rule.lookback == 19
    assert compile_rule('close > avwap("s")').lookback is None  # sums since the anchor
    assert not compile_rule("close > sma(close, 20)").user_scoped


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('close > drawing("s")', "needs an output"),
        ('close > drawing("s").middle', "no output 'middle'"),
        ('close > avwap("s").top', "no output 'top'"),
        ('weekly.close > weekly.drawing("s").price', "no weekly form"),
        ("close > drawing", "write drawing"),
        ("close > avwap(5)", "label in quotes"),
        ('close > sma("x")', "a string is allowed only"),
        ('close > drawing("").price', "needs a drawing's label"),
        ('close > drawing("' + "x" * 81 + '").price', "at most 80"),
        ('drawing("s").price', "must be a condition"),
    ],
)
def test_type_and_syntax_errors(text: str, message: str) -> None:
    with pytest.raises(RuleError) as exc:
        compile_rule(text)
    assert message in exc.value.message


# --- values per kind ---------------------------------------------------------


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


DAYS = _weekdays(date(2025, 1, 6), 40)  # Mon 6 Jan onwards


def _data(drawings: Drawings | None, closes=None) -> SymbolData:
    closes = closes if closes is not None else [100.0 + i for i in range(len(DAYS))]
    rows = [
        (d, c, c + 1, c - 1, c, 1000.0 + i)
        for i, (d, c) in enumerate(zip(DAYS, closes, strict=True))
    ]
    return SymbolData("AAPL", "XNYS", bars_frame(rows), drawings=drawings)


def _num(text: str, data: SymbolData) -> pd.Series:
    return vector_of(compile_rule(text, require_condition=False), data)


def _ref(*items: DrawingRef) -> Drawings:
    return Drawings(1, items)


def test_hline_is_its_price_on_every_bar() -> None:
    data = _data(_ref(DrawingRef(1, "hline", "Support", ((None, 110.5),))))
    values = _num('drawing("support").price', data)
    assert (values == 110.5).all()
    met = vector_of(compile_rule('close > drawing("support").price'), data)
    assert not met.iloc[10] and met.iloc[11]


def test_trendline_is_linear_in_weekdays_between_its_anchors_only() -> None:
    # 10 Jan (Fri) at 100 to 24 Jan (Fri) at 120: 10 weekdays, 2 a weekday.
    tl = DrawingRef(1, "trendline", "t", ((date(2025, 1, 24), 120.0), (date(2025, 1, 10), 100.0)))
    values = _num('drawing("t").price', _data(_ref(tl)))
    by_day = dict(zip(DAYS, values, strict=True))
    assert math.isnan(by_day[date(2025, 1, 9)])  # before the first anchor
    assert by_day[date(2025, 1, 10)] == pytest.approx(100.0)
    assert by_day[date(2025, 1, 13)] == pytest.approx(102.0)  # Monday: one weekday on
    assert by_day[date(2025, 1, 17)] == pytest.approx(110.0)
    assert by_day[date(2025, 1, 24)] == pytest.approx(120.0)
    assert math.isnan(by_day[date(2025, 1, 27)])  # not extended past its end
    outcome, _ = evaluate_at(compile_rule('close > drawing("t").price'), _data(_ref(tl)), DAYS[0])
    assert outcome.status == "unknown"
    assert "before its first anchor on 2025-01-10" in outcome.reasons[0]
    outcome, _ = evaluate_at(compile_rule('close > drawing("t").price'), _data(_ref(tl)), DAYS[-1])
    assert "after the line ends on 2025-01-24" in outcome.reasons[0]


def test_ray_extends_past_its_second_point_and_a_leftward_ray_runs_back() -> None:
    right = DrawingRef(1, "ray", "r", ((date(2025, 1, 10), 100.0), (date(2025, 1, 17), 105.0)))
    left = DrawingRef(2, "ray", "l", ((date(2025, 1, 17), 105.0), (date(2025, 1, 10), 100.0)))
    data = _data(_ref(right, left))
    r = dict(zip(DAYS, _num('drawing("r").price', data), strict=True))
    assert math.isnan(r[date(2025, 1, 9)])
    assert r[date(2025, 1, 24)] == pytest.approx(110.0)  # extended
    assert r[DAYS[-1]] == pytest.approx(100.0 + (len(DAYS) - 5) * 1.0)
    lv = dict(zip(DAYS, _num('drawing("l").price', data), strict=True))
    assert lv[date(2025, 1, 6)] == pytest.approx(96.0)  # four weekdays before 10 Jan
    assert math.isnan(lv[date(2025, 1, 20)])


def test_rectangle_top_and_bottom_from_its_left_edge_on() -> None:
    box = DrawingRef(
        1, "rectangle", "zone", ((date(2025, 1, 15), 120.0), (date(2025, 1, 8), 105.0))
    )
    data = _data(_ref(box))
    top = dict(zip(DAYS, _num('drawing("zone").top', data), strict=True))
    bottom = dict(zip(DAYS, _num('drawing("zone").bottom', data), strict=True))
    assert math.isnan(top[date(2025, 1, 7)]) and top[date(2025, 1, 8)] == 120.0
    assert bottom[DAYS[-1]] == 105.0  # the zone keeps its level
    outcome, _ = evaluate_at(compile_rule('close > drawing("zone").price'), data, DAYS[-1])
    assert outcome.reasons == ("drawing 'zone' is a rectangle: read .top or .bottom",)


def test_avwap_binding_equals_the_api_maths() -> None:
    data = _data(_ref(DrawingRef(1, "avwap", "swing", ((date(2025, 1, 13), None),))))
    got = _num('avwap("swing")', data).to_numpy()
    bars = data.bars
    want = avwap_math.compute(
        DAYS, bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy(),
        bars["volume"].to_numpy(), date(2025, 1, 13),
    )  # fmt: skip
    np.testing.assert_array_equal(got, want.vwap)
    upper = _num('avwap("swing").upper1', data).to_numpy()
    np.testing.assert_array_equal(upper, want.band(1))
    assert point('close > avwap("swing")', data, DAYS[6]) is True
    assert point('close > avwap("swing")', data, DAYS[4]) is None  # before the anchor


@pytest.mark.parametrize(
    ("items", "rule", "reason"),
    [
        ((), 'close > drawing("s").price', "drawing 's' not found"),
        ((), 'close > avwap("s")', "anchored VWAP 's' not found"),
        (
            (
                DrawingRef(1, "hline", "s", ((None, 1.0),)),
                DrawingRef(2, "hline", "S", ((None, 2.0),)),
            ),
            'close > drawing("s").price',
            "2 of your drawings are labelled 's'",
        ),
        (
            (DrawingRef(1, "text", "s", ((date(2025, 1, 8), 1.0),)),),
            'close > drawing("s").price',
            "is a text",
        ),
        (
            (DrawingRef(1, "hline", "s", ((None, 1.0),)),),
            'close > drawing("s").top',
            "is a hline: read .price",
        ),
        (
            (DrawingRef(1, "avwap", "s", ((date(2025, 1, 8), None),)),),
            'close > drawing("s").price',
            "drawing 's' not found",  # an AVWAP is read with avwap()
        ),
        (
            (DrawingRef(1, "trendline", "s", ((date(2025, 1, 8), 1.0), (date(2025, 1, 8), 2.0))),),
            'close > drawing("s").price',
            "both anchors on the same day",
        ),
    ],
)
def test_unknown_with_a_reason(items, rule: str, reason: str) -> None:
    outcome, _ = evaluate_at(compile_rule(rule), _data(_ref(*items)), DAYS[-1])
    assert outcome.status == "unknown"
    assert any(reason in r for r in outcome.reasons), outcome.reasons


def test_without_an_owner_every_drawing_value_is_unknown() -> None:
    outcome, _ = evaluate_at(compile_rule('close > drawing("s").price'), _data(None), DAYS[-1])
    assert outcome.status == "unknown"
    assert "run only for their owner" in outcome.reasons[0]
    # Kleene: an unknown drawing does not block a true "or".
    either = compile_rule('close > 0 or close > drawing("s").price')
    assert evaluate_at(either, _data(None), DAYS[-1])[0].status == "met"


def test_a_drawing_after_t_never_leaks_into_point_mode() -> None:
    later = DrawingRef(1, "trendline", "t", ((date(2025, 2, 3), 100.0), (date(2025, 2, 14), 150.0)))
    data = _data(_ref(later))
    rule = compile_rule('close > drawing("t").price', require_condition=False)
    full = vector_of(rule, data)
    for t in DAYS:
        want = full[pd.Timestamp(t)]
        got = point(rule, data, t)
        assert (got is None and want is pd.NA) or got == bool(want)
    changed = data.bars.copy()
    changed.loc[changed.index > pd.Timestamp(date(2025, 2, 5)), "close"] *= 3
    again = vector_of(rule, replace(data, bars=changed))
    head = full.loc[: pd.Timestamp(date(2025, 2, 5))]
    assert head.equals(again.loc[: pd.Timestamp(date(2025, 2, 5))])


# --- the database: user scoping, presets, forks, screener, alerts, CLI --------


def _user(session: Session, email: str) -> int:
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _bars(session: Session, ticker: str = "AAPL", n: int = 40, start: float = 100.0) -> list[date]:
    days = _weekdays(date(2025, 1, 6), n)
    for i, day in enumerate(days):
        c = Decimal(str(start + i))
        session.add(
            PriceBar(
                ticker=ticker, ts=datetime.combine(day, datetime.min.time()), interval="1d",
                open=c, high=c + 1, low=c - 1, close=c, volume=1000, source="test",
            )
        )  # fmt: skip
    session.commit()
    return days


def _draw(session: Session, user_id: int, kind: str, label: str, points, ticker="AAPL") -> Drawing:
    iid = instrument_ids(session, [ticker])[ticker]
    row = Drawing(
        user_id=user_id, instrument_id=iid, kind=kind, points=points, style={}, label=label
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


RULE = 'close > drawing("support").price'


def test_only_the_owner_resolves_a_drawing(session: Session) -> None:
    seed_symbols(session, "AAPL")
    days = _bars(session)
    me, other = _user(session, "me@x.dev"), _user(session, "other@x.dev")
    _draw(session, me, "hline", "Support", [{"ts": None, "price": "120"}])
    rule = compile_rule(RULE)
    end = days[-1]
    mine = load_symbol(session, "AAPL", end=end, needs=rule.needs, user_id=me)
    theirs = load_symbol(session, "AAPL", end=end, needs=rule.needs, user_id=other)
    nobody = load_symbol(session, "AAPL", end=end, needs=rule.needs)
    assert evaluate_at(rule, mine, end)[0].status == "met"  # 139 > 120
    assert evaluate_at(rule, theirs, end)[0].reasons == ("drawing 'support' not found",)
    assert "only for their owner" in evaluate_at(rule, nobody, end)[0].reasons[0]


def test_presets_refuse_user_scoped_rules_and_others_cannot_fork(session: Session) -> None:
    seed_symbols(session, "AAPL")
    me, other = _user(session, "me@x.dev"), _user(session, "other@x.dev")
    preset = Preset("x-drawings", "Uses drawings", "screen", "test", RULE)
    with pytest.raises(store.UserScopedRule):
        seed_setups(session, (preset,))
    setup, version = store.create_setup(
        session, me, name="Mine", kind="screen", rule=compile_rule(RULE)
    )
    # The owner may fork their own; another user may not (the router 404s first anyway).
    store.fork(session, setup, me, version=version)
    with pytest.raises(store.UserScopedRule):
        store.fork(session, setup, other, version=version)
    # A preset row can never take a user-scoped version.
    seed_setups(session, (Preset("x-plain", "Plain", "screen", "test", "close > 1"),))
    system = session.exec(select(Setup).where(Setup.preset_key == "x-plain")).one()
    with pytest.raises(store.UserScopedRule):
        store.add_version(session, system, compile_rule(RULE))


def test_rules_check_reports_user_scoped(client: TestClient) -> None:
    body = client.post("/v1/rules/check", json={"rule": RULE}).json()
    assert body["valid"] and body["user_scoped"] and "drawings" in body["uses"]
    plain = client.post("/v1/rules/check", json={"rule": "close > 1"}).json()
    assert plain["user_scoped"] is False


def test_setup_versions_say_user_scoped_and_forks_by_others_are_refused(
    session: Session, client: TestClient
) -> None:
    me, other = _user(session, "me@x.dev"), _user(session, "other@x.dev")
    created = client.post(
        "/v1/setups", json={"name": "Mine", "kind": "screen", "rule": RULE}, headers=_auth(me)
    )
    assert created.status_code == 201, created.text
    assert created.json()["latest_version"]["user_scoped"] is True
    sid = created.json()["id"]
    assert client.post(f"/v1/setups/{sid}/fork", headers=_auth(me)).status_code == 201
    assert client.post(f"/v1/setups/{sid}/fork", headers=_auth(other)).status_code == 404


def test_the_screener_runs_a_user_scoped_rule_for_the_signed_in_user_only(
    session: Session, client: TestClient
) -> None:
    seed_symbols(session, "AAPL", "MSFT")
    days = _bars(session, "AAPL")
    _bars(session, "MSFT", start=50.0)
    me, other = _user(session, "me@x.dev"), _user(session, "other@x.dev")
    _draw(session, me, "hline", "support", [{"ts": None, "price": "120"}])
    _draw(session, other, "hline", "support", [{"ts": None, "price": "500"}])
    refresh_symbol_metrics(session)
    session.commit()
    params = {"rule": RULE, "as_of": days[-1].isoformat(), "rule_mode": "all"}
    anonymous = client.get("/v1/screener", params=params)
    assert anonymous.status_code == 401 and "sign in" in anonymous.json()["detail"]
    mine = client.get("/v1/screener", params=params, headers=_auth(me)).json()
    rows = {r["ticker"]: r for r in mine["rows"]}
    assert rows["AAPL"]["rule_result"] == "met"
    assert rows["MSFT"]["rule_result"] == "unknown"  # no drawing of mine there
    assert "drawing 'support' not found" in rows["MSFT"]["rule_reason"]
    assert mine["rule"]["user_scoped"] is True and mine["rule"]["cached"] is False
    theirs = client.get("/v1/screener", params=params, headers=_auth(other)).json()
    assert {r["ticker"]: r["rule_result"] for r in theirs["rows"]}["AAPL"] == "not_met"


def test_a_deleted_or_renamed_drawing_is_unknown_and_the_alert_stays_quiet(
    session: Session,
) -> None:
    seed_symbols(session, "AAPL")
    _bars(session, n=20)
    me = _user(session, "me@x.dev")
    row = _draw(session, me, "hline", "support", [{"ts": None, "price": "200"}])
    _setup, version = store.create_setup(
        session, me, name="Over", kind="alert", rule=compile_rule(RULE)
    )
    alert = Alert(user_id=me, ticker="AAPL", kind=AlertKind.RULE, setup_version_id=version.id,
                  params={"setup_name": "Over", "version": 1, "canonical": RULE})  # fmt: skip
    session.add(alert)
    session.commit()
    assert evaluate_pending_alerts(session) == 0  # 119 < 200: not true

    row.label = "old support"  # renamed
    session.add(row)
    session.commit()
    rule = compile_rule(RULE)
    days = _weekdays(date(2025, 1, 6), 22)
    end = days[-1]
    for i, day in enumerate(days[20:], start=20):
        c = Decimal(300 + i)  # far above the old level
        session.add(PriceBar(ticker="AAPL", ts=datetime.combine(day, datetime.min.time()),
                             interval="1d", open=c, high=c, low=c, close=c, volume=1,
                             source="test"))  # fmt: skip
    session.commit()
    data = load_symbol(session, "AAPL", end=end, needs=rule.needs, user_id=me)
    assert evaluate_at(rule, data, end)[0].reasons == ("drawing 'support' not found",)
    assert evaluate_pending_alerts(session) == 0  # unknown never fires
    session.delete(row)
    session.commit()
    data = load_symbol(session, "AAPL", end=end, needs=rule.needs, user_id=me)
    assert evaluate_at(rule, data, end)[0].status == "unknown"
    assert session.exec(select(AlertEvent)).first() is None


def test_the_alert_fires_on_the_owners_drawing(session: Session) -> None:
    seed_symbols(session, "AAPL")
    _bars(session, n=20)  # closes 100..119
    me = _user(session, "me@x.dev")
    _draw(session, me, "hline", "support", [{"ts": None, "price": "125"}])
    _setup, version = store.create_setup(
        session, me, name="Over", kind="alert", rule=compile_rule(RULE)
    )
    session.add(Alert(user_id=me, ticker="AAPL", kind=AlertKind.RULE, setup_version_id=version.id,
                      params={"setup_name": "Over", "version": 1, "canonical": RULE}))  # fmt: skip
    session.commit()
    assert evaluate_pending_alerts(session) == 0
    day = _weekdays(date(2025, 1, 6), 21)[-1]
    session.add(PriceBar(ticker="AAPL", ts=datetime.combine(day, datetime.min.time()),
                         interval="1d", open=Decimal(130), high=Decimal(130), low=Decimal(130),
                         close=Decimal(130), volume=1, source="test"))  # fmt: skip
    session.commit()
    assert evaluate_pending_alerts(session) == 1


def test_rule_check_cli_with_and_without_user_id(
    session: Session, engine, monkeypatch, capsys
) -> None:
    seed_symbols(session, "AAPL")
    days = _bars(session)
    me = _user(session, "me@x.dev")
    _draw(session, me, "avwap", "swing", [{"ts": days[5].isoformat(), "price": None}])
    monkeypatch.setattr(cli, "engine", engine)
    rule = 'close > avwap("swing")'
    code = cli.main(["rule-check", rule, "AAPL", "--date", days[-1].isoformat(),
                     "--user-id", str(me), "--explain"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert f"judged for user {me}" in out and f"AAPL {days[-1].isoformat()}: met" in out
    assert '  avwap("swing") = ' in out
    cli.main(["rule-check", rule, "AAPL", "--date", days[-1].isoformat()])
    out = capsys.readouterr().out
    assert "pass --user-id" in out and ": unknown" in out and "only for their owner" in out
