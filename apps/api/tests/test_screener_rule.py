"""A2.2 (M4.3): the screener running a Rule DSL rule after its SQL filters."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.services.dsl import compile_rule
from stockviz.services.markets.calendar import is_session
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.screener import ScreenQuery, run_screen_full
from stockviz.services.setups.presets import seed_presets
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
AS_OF = date(2025, 6, 10)  # a Tuesday, a session on XNYS and XNSE
RULE = "close > sma(close, 50)"


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _sessions(venue: str, end: date, n: int) -> list[date]:
    out: list[date] = []
    day = end
    while len(out) < n:
        if is_session(day, venue):
            out.append(day)
        day -= timedelta(days=1)
    return out[::-1]


def _bars(session: Session, ticker: str, days: list[date], step: float) -> None:
    for i, day in enumerate(days):
        close = Decimal(str(round(100 + step * i, 2)))
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime(day.year, day.month, day.day),
                interval="1d",
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000 + i,
                source="test",
            )
        )


def _seed(session: Session) -> None:
    seed_symbols(session, "AAPL", "MSFT", "KO", "NEWCO", "STALE")
    seed_symbols(session, "INFY.NS", currency="INR")
    us = _sessions("XNYS", AS_OF, 260)
    _bars(session, "AAPL", us, 0.5)  # rising: met
    _bars(session, "MSFT", us, -0.2)  # falling: not met
    _bars(session, "KO", us, 0.0)  # flat: close = average, not met
    _bars(session, "NEWCO", us[-30:], 0.5)  # 30 bars: not enough for sma 50
    _bars(session, "STALE", us[:-4], 0.5)  # stopped four sessions ago
    _bars(session, "INFY.NS", _sessions("XNSE", AS_OF, 260), 1.0)
    session.commit()
    refresh_symbol_metrics(session)
    session.commit()


def _get(client: TestClient, **params) -> dict:
    res = client.get("/v1/screener", params={"as_of": AS_OF.isoformat(), **params})
    assert res.status_code == 200, res.text
    return res.json()


def test_met_only_is_the_default(session: Session, client: TestClient) -> None:
    _seed(session)
    body = _get(client, rule=RULE)
    assert [r["ticker"] for r in body["rows"]] == ["AAPL", "INFY.NS"]
    assert body["total"] == 2
    assert all(r["rule_result"] == "met" and r["rule_reason"] is None for r in body["rows"])
    assert body["rows"][0]["rule_bar_date"] == AS_OF.isoformat()
    rule = body["rule"]
    assert rule["canonical"] == RULE and rule["hash"] == compile_rule(RULE).hash
    assert rule["mode"] == "met_only" and rule["as_of"] == AS_OF.isoformat()
    assert rule["counts"] == {"met": 2, "not_met": 2, "unknown": 2}
    assert rule["evaluated"] == 6
    assert rule["sessions"] == {"XNYS": AS_OF.isoformat(), "XNSE": AS_OF.isoformat()}


def test_all_mode_shows_every_row_with_reasons(session: Session, client: TestClient) -> None:
    _seed(session)
    body = _get(client, rule=RULE, rule_mode="all")
    by = {r["ticker"]: r for r in body["rows"]}
    assert body["total"] == 6
    assert {t: r["rule_result"] for t, r in by.items()} == {
        "AAPL": "met",
        "INFY.NS": "met",
        "MSFT": "not_met",
        "KO": "not_met",
        "NEWCO": "unknown",
        "STALE": "unknown",
    }
    assert "history" in by["NEWCO"]["rule_reason"]
    stale_last = _sessions("XNYS", AS_OF, 5)[0]
    assert by["STALE"]["rule_reason"] == (
        f"no bar for {AS_OF.isoformat()}; latest {stale_last.isoformat()}"
    )
    assert by["STALE"]["rule_bar_date"] == stale_last.isoformat()
    assert by["MSFT"]["rule_reason"] is None


def test_filters_prefilter_and_paging_after_the_rule(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    india = _get(client, rule=RULE, rule_mode="all", market="IN")
    assert [r["ticker"] for r in india["rows"]] == ["INFY.NS"]
    assert india["rule"]["evaluated"] == 1
    assert india["rule"]["sessions"] == {"XNSE": AS_OF.isoformat()}

    page1 = _get(client, rule=RULE, rule_mode="all", sort="ticker", limit=2)
    page2 = _get(client, rule=RULE, rule_mode="all", sort="ticker", limit=2, offset=2)
    assert page1["total"] == page2["total"] == 6
    assert [r["ticker"] for r in page1["rows"]] == ["AAPL", "INFY.NS"]
    assert [r["ticker"] for r in page2["rows"]] == ["KO", "MSFT"]


def test_survivorship_stamp_on_every_page(session: Session, client: TestClient) -> None:
    _seed(session)
    for body in (_get(client), _get(client, rule=RULE)):
        universe = body["universe"]
        assert universe["name"] == "pinned"
        assert universe["point_in_time"] is False and universe["survivorship_biased"] is True
        assert "survivorship" in universe["note"]
    assert _get(client)["rule"] is None


def test_bad_rule_is_422_with_its_column(session: Session, client: TestClient) -> None:
    _seed(session)
    res = client.get("/v1/screener", params={"rule": "close > sma(close, 50) andd 1"})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["kind"] == "syntax" and detail["line"] == 1 and detail["column"] == 24
    res = client.get("/v1/screener", params={"rule": "close"})
    assert res.status_code == 422 and res.json()["detail"]["kind"] == "type"


def test_setup_version_id_presets_public_private_for_owner(
    session: Session, client: TestClient
) -> None:
    _seed(session)
    seed_presets(session)
    user = User(email="o@x.dev", name="o")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    other = User(email="p@x.dev", name="p")
    session.add(other)
    session.commit()
    session.refresh(other)
    assert other.id is not None

    presets = client.get("/v1/setups", headers=_auth(user.id)).json()
    preset_vid = presets[0]["latest_version"]["id"]
    body = _get(client, setup_version_id=preset_vid, rule_mode="all")
    assert body["rule"]["setup_version_id"] == preset_vid
    assert body["rule"]["hash"] == presets[0]["latest_version"]["rule_hash"]

    mine = client.post(
        "/v1/setups", json={"name": "Mine", "rule": RULE}, headers=_auth(user.id)
    ).json()["latest_version"]["id"]
    anon = client.get("/v1/screener", params={"setup_version_id": mine})
    assert anon.status_code == 404
    theirs = client.get(
        "/v1/screener", params={"setup_version_id": mine}, headers=_auth(other.id)
    )
    assert theirs.status_code == 404
    owner = client.get(
        "/v1/screener",
        params={"setup_version_id": mine, "as_of": AS_OF.isoformat()},
        headers=_auth(user.id),
    )
    assert owner.status_code == 200 and owner.json()["total"] == 2

    both = client.get("/v1/screener", params={"setup_version_id": mine, "rule": RULE})
    assert both.status_code == 400


def test_as_of_judges_an_earlier_session(session: Session, client: TestClient) -> None:
    _seed(session)
    earlier = _sessions("XNYS", AS_OF, 10)[0]
    body = _get(client, rule=RULE, rule_mode="all", as_of=earlier.isoformat())
    by = {r["ticker"]: r for r in body["rows"]}
    assert body["rule"]["sessions"]["XNYS"] == earlier.isoformat()
    # STALE still had bars then, so it is judged (and met: it was rising).
    assert by["STALE"]["rule_result"] == "met"
    assert by["AAPL"]["rule_bar_date"] == earlier.isoformat()


def test_results_are_cached_per_rule_and_session(session: Session) -> None:
    _seed(session)
    q = ScreenQuery(
        rule=compile_rule(RULE),
        rule_mode="all",
        as_of=AS_OF,
        now=datetime(2025, 6, 11, tzinfo=UTC),
    )
    first = run_screen_full(session, q)
    assert first.rule_run.cached is False
    second = run_screen_full(session, q)
    assert second.rule_run.cached is True
    assert second.counts == first.counts
