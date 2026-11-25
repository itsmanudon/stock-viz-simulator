"""A3.5: the events endpoint (M2.8), RS percentile and delivery (M2.7), the
market regime (M3.1)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import (
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    CorporateAction,
    Dividend,
    EarningsEvent,
    Portfolio,
    PriceBar,
    Symbol,
    SymbolMetrics,
    Trade,
    User,
)
from stockviz.models.data_file import DataFile
from stockviz.models.eod import EodExtras
from stockviz.models.portfolio import TradeSide
from stockviz.services import regime
from stockviz.services.delivery_pct import resample_points, with_average
from stockviz.services.instruments import instrument_ids
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.relative_strength import percentile, relative_strength
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


@pytest.fixture(autouse=True)
def _fresh_regime_cache():
    regime.clear_cache()
    yield
    regime.clear_cache()


# --- events -------------------------------------------------------------------


def _symbols(session: Session, *tickers: str) -> None:
    for t in tickers:
        session.add(Symbol(ticker=t, name=t, currency="INR" if t.endswith(".NS") else "USD"))
    session.commit()


def _doc(session: Session, doc_id: str, ticker: str, at: datetime, source: str = "Reuters"):
    entity = f"ent_{ticker}"
    if session.get(AegisMapping, f"map_{ticker}") is None:
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}",
                entity_id=entity,
                scheme="provider_id",
                identifier=f"stockviz:{ticker}",
                created_at=datetime(2026, 1, 1),
            )
        )
    session.add(
        AegisDocument(
            document_id=doc_id,
            source_id="src",
            source_name=source,
            title=f"Headline {doc_id}",
            url=f"https://news.example.test/{doc_id}",
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
            resolution_analysis_id=f"res_{doc_id}",
            confidence=1.0,
        )
    )
    session.commit()


def _user_with_portfolio(session: Session, email: str) -> tuple[int, int]:
    user = User(email=email, name=email)
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    portfolio = Portfolio(user_id=user.id, cash_balance=Decimal("100000"))
    session.add(portfolio)
    session.commit()
    session.refresh(portfolio)
    assert portfolio.id is not None
    return user.id, portfolio.id


def _seed_events(session: Session) -> tuple[int, int]:
    _symbols(session, "AAPL", "MSFT")
    _doc(session, "d1", "AAPL", datetime(2025, 3, 3, 9), "Reuters")
    _doc(session, "d2", "AAPL", datetime(2025, 3, 3, 21), "AP")
    _doc(session, "d3", "AAPL", datetime(2025, 3, 3, 23, 59), "Reuters")
    _doc(session, "d4", "AAPL", datetime(2025, 3, 8, 12), "AP")  # a Saturday
    _doc(session, "m1", "MSFT", datetime(2025, 3, 3, 10))
    session.add(EarningsEvent(ticker="AAPL", event_date=date(2025, 1, 30), fiscal_period="Q1",
                              report_time="AMC", eps_estimate=Decimal("2.35"),
                              eps_actual=Decimal("2.40")))  # fmt: skip
    session.add(Dividend(ticker="AAPL", ex_date=date(2025, 2, 10), amount=Decimal("0.25")))
    session.add(CorporateAction(ticker="AAPL", kind="split", ex_date=date(2020, 8, 31),
                                ratio_from=Decimal(1), ratio_to=Decimal(4), source="test"))  # fmt: skip
    session.commit()
    alice, alice_pf = _user_with_portfolio(session, "alice@example.test")
    bob, bob_pf = _user_with_portfolio(session, "bob@example.test")
    for pf, side, qty, day in (
        (alice_pf, TradeSide.BUY, "10", datetime(2025, 2, 3, 21)),
        (alice_pf, TradeSide.SELL, "4", datetime(2025, 3, 4, 21)),
        (bob_pf, TradeSide.BUY, "99", datetime(2025, 2, 5, 21)),
    ):
        session.add(Trade(portfolio_id=pf, ticker="AAPL", side=side, quantity=Decimal(qty),
                          price=Decimal("200"), ts=day, fx_rate=Decimal(1)))  # fmt: skip
    session.commit()
    return alice, bob


def test_events_merge_every_public_type_in_date_order(session, client: TestClient) -> None:
    _seed_events(session)
    body = client.get("/v1/symbols/AAPL/events?from=2020-01-01&to=2025-12-31").json()
    assert body["from"] == "2020-01-01" and body["to"] == "2025-12-31"
    assert body["types"] == ["news", "earnings", "dividend", "split"]
    assert body["fills_included"] is False
    kinds = [(e["type"], e["date"]) for e in body["events"]]
    assert kinds == [
        ("split", "2020-08-31"),
        ("earnings", "2025-01-30"),
        ("dividend", "2025-02-10"),
        ("news", "2025-03-03"),
        ("news", "2025-03-08"),
    ]
    split = body["events"][0]
    assert Decimal(split["ratio_from"]) == 1 and Decimal(split["ratio_to"]) == 4
    dividend = body["events"][2]
    assert Decimal(dividend["amount"]) == Decimal("0.25") and dividend["currency"] == "USD"


def test_news_clusters_by_available_day_with_sources_and_no_text(session, client) -> None:
    _seed_events(session)
    body = client.get("/v1/symbols/AAPL/events?from=2025-03-01&to=2025-03-31&types=news").json()
    day = body["events"][0]
    assert day["date"] == "2025-03-03" and day["count"] == 3
    assert day["sources"] == ["AP", "Reuters"]
    assert {h["id"] for h in day["headlines"]} == {"d1", "d2", "d3"}
    headline = day["headlines"][0]
    assert set(headline) == {"id", "title", "source", "url", "available_at", "published_at"}
    assert "MSFT" not in str(body)  # another symbol's document never joins
    assert body["news_rule"].startswith("One marker per UTC day")


def test_news_counts_match_the_news_endpoint_per_day(session, client) -> None:
    _seed_events(session)
    news = client.get("/v1/symbols/AAPL/news?limit=100").json()
    per_day: dict[str, int] = {}
    for item in news:
        per_day[item["available_at"][:10]] = per_day.get(item["available_at"][:10], 0) + 1
    events = client.get("/v1/symbols/AAPL/events?from=2025-01-01&to=2025-12-31&types=news").json()
    assert {e["date"]: e["count"] for e in events["events"]} == per_day


def test_types_filter_and_date_range(session, client) -> None:
    _seed_events(session)
    body = client.get("/v1/symbols/AAPL/events?from=2025-02-01&to=2025-03-05&types=dividend,news")
    assert [(e["type"], e["date"]) for e in body.json()["events"]] == [
        ("dividend", "2025-02-10"),
        ("news", "2025-03-03"),
    ]
    assert client.get("/v1/symbols/AAPL/events?types=bogus").status_code == 400
    assert client.get("/v1/symbols/AAPL/events?from=2025-03-02&to=2025-03-01").status_code == 400
    assert client.get("/v1/symbols/AAPL/events?from=1990-01-01&to=2025-03-01").status_code == 400
    assert client.get("/v1/symbols/NOPE/events").status_code == 404


def test_fills_are_the_callers_own_and_never_anonymous(session, client) -> None:
    alice, bob = _seed_events(session)
    url = "/v1/symbols/AAPL/events?from=2025-01-01&to=2025-12-31"
    anon = client.get(url + "&types=fill").json()
    assert anon["events"] == [] and anon["fills_included"] is False

    mine = client.get(url + "&types=fill", headers=_auth(alice)).json()
    assert mine["fills_included"] is True
    assert [(e["side"], Decimal(e["quantity"])) for e in mine["events"]] == [
        ("buy", Decimal(10)),
        ("sell", Decimal(4)),
    ]
    assert all(e["r_multiple"] is None for e in mine["events"])
    theirs = client.get(url + "&types=fill", headers=_auth(bob)).json()
    assert [Decimal(e["quantity"]) for e in theirs["events"]] == [Decimal(99)]

    # With a token the default types add the caller's fills.
    default = client.get(url, headers=_auth(alice)).json()
    assert "fill" in default["types"]
    assert sum(1 for e in default["events"] if e["type"] == "fill") == 2
    bad = client.get(url, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


# --- relative strength --------------------------------------------------------


def _bars(session: Session, ticker: str, closes: list[float], start: date) -> None:
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        session.add(PriceBar(ticker=ticker, ts=datetime.combine(day, datetime.min.time()),
                             interval="1d", open=Decimal(str(close)),
                             high=Decimal(str(close * 1.01)), low=Decimal(str(close * 0.99)),
                             close=Decimal(str(close)), volume=1000, source="test"))  # fmt: skip
        day += timedelta(days=1)
    session.commit()


def test_percentile_counts_lower_and_half_the_ties() -> None:
    assert percentile(5, [1, 2, 3, 4]) == 100
    assert percentile(1, [2, 3, 4, 5]) == 0
    assert percentile(3, [1, 3, 5, 7]) == pytest.approx(100 * (1 + 0.5) / 4)
    assert percentile(3, [1, 2]) is None  # fewer than MIN_UNIVERSE members


def test_rs_percentile_and_52_week_distance(session, client) -> None:
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "RELIANCE.NS"]
    _symbols(session, *tickers)
    start = date(2024, 1, 1)
    # A steady daily growth rate per symbol; AAA strongest, EEE weakest.
    for i, ticker in enumerate(tickers[:5]):
        g = 0.002 - i * 0.001
        _bars(session, ticker, [100 * math.exp(g * k) for k in range(300)], start)
    _bars(session, "RELIANCE.NS", [100 * math.exp(0.01 * k) for k in range(300)], start)
    refresh_symbol_metrics(session)

    rs = relative_strength(session, "AAA")
    assert rs.market == "US" and rs.benchmark == "^GSPC" and rs.universe_size == 5
    assert [p.percentile for p in rs.periods] == [100, 100, 100, 100]
    assert rs.periods[0].return_pct == pytest.approx((math.exp(0.002 * 21) - 1) * 100)
    weak = relative_strength(session, "EEE")
    assert [p.percentile for p in weak.periods] == [0, 0, 0, 0]
    mid = relative_strength(session, "CCC")
    assert mid.periods[1].percentile == 50
    # The Indian symbol ranks only within India (one member: no percentile).
    india = relative_strength(session, "RELIANCE.NS")
    assert india.market == "IN" and india.universe_size == 1
    assert all(p.percentile is None for p in india.periods)

    # A falling symbol: its close against its 252-session high.
    body = client.get("/v1/symbols/EEE/relative-strength").json()
    row = session.get(SymbolMetrics, instrument_ids(session, ["EEE"])["EEE"])
    assert row is not None and row.high_52w is not None and row.last_close is not None
    expected = (float(row.last_close) / float(row.high_52w) - 1) * 100
    assert body["distance_from_high_52w_pct"] == pytest.approx(expected)
    assert expected < 0
    assert body["universe"] == {
        "market": "US",
        "size": 5,
        "as_of": body["as_of"],
        "point_in_time": False,
        "survivorship_biased": True,
        "note": "Current symbol list, not point in time: survivorship-biased.",
    }
    assert [p["period"] for p in body["periods"]] == ["1m", "3m", "6m", "12m"]
    detail = client.get("/v1/symbols/AAA").json()
    assert detail["market"] == "US" and detail["benchmark"] == "^GSPC"
    assert detail["benchmark_name"] == "S&P 500" and detail["is_indian"] is False
    assert client.get("/v1/symbols/RELIANCE.NS").json()["is_indian"] is True


def test_short_history_has_no_long_returns(session) -> None:
    _symbols(session, "NEW")
    _bars(session, "NEW", [10 + k for k in range(30)], date(2025, 1, 1))
    refresh_symbol_metrics(session)
    row = session.get(SymbolMetrics, instrument_ids(session, ["NEW"])["NEW"])
    assert row is not None
    assert row.return_1m == pytest.approx((39 / 18 - 1) * 100)
    assert row.return_3m is None and row.return_12m is None


# --- delivery -----------------------------------------------------------------


def test_delivery_average_needs_twenty_sessions() -> None:
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(25)]
    points = with_average([(d, float(i)) for i, d in enumerate(days)])
    assert all(p.avg_20 is None for p in points[:19])
    assert points[19].avg_20 == pytest.approx(sum(range(20)) / 20)
    assert points[24].avg_20 == pytest.approx(sum(range(5, 25)) / 20)
    weekly = resample_points(points, "1wk")
    assert weekly[-1].day == days[-1] and weekly[-1].avg_20 == points[-1].avg_20


def test_delivery_route_empty_state_and_data(session, client) -> None:
    _symbols(session, "AAPL", "RELIANCE.NS")
    us = client.get("/v1/symbols/AAPL/delivery").json()
    assert us["applicable"] is False and us["points"] == []
    empty = client.get("/v1/symbols/RELIANCE.NS/delivery").json()
    assert empty["applicable"] is True and empty["has_data"] is False
    assert empty["note"].startswith("No delivery data yet")

    iid = instrument_ids(session, ["RELIANCE.NS"])["RELIANCE.NS"]
    session.add(DataFile(id=1, source="nse_sec_full", file_name="x.csv", sha256="0" * 64,
                         size_bytes=1, archived_path="x", parse_status="parsed"))  # fmt: skip
    session.flush()
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(22)]
    for i, d in enumerate(days):
        session.add(EodExtras(instrument_id=iid, session_date=d, series="EQ",
                              delivery_pct=Decimal(40 + i), data_file_id=1))  # fmt: skip
    # A second series on the last day: EQ still wins.
    session.add(EodExtras(instrument_id=iid, session_date=days[-1], series="BE",
                          delivery_pct=Decimal("1"), data_file_id=1))  # fmt: skip
    session.commit()
    body = client.get("/v1/symbols/RELIANCE.NS/delivery").json()
    assert body["has_data"] is True and len(body["points"]) == 22
    last = body["points"][-1]
    assert last["delivery_pct"] == 61
    assert last["avg_20"] == pytest.approx(sum(range(42, 62)) / 20)
    ranged = client.get("/v1/symbols/RELIANCE.NS/delivery?from=2025-01-20").json()
    assert ranged["points"][0]["ts"] == "2025-01-20"


# --- regime -------------------------------------------------------------------


def _values(close, sma, breadth, vol) -> dict[str, float | None]:
    return {"index_close": close, "index_sma_200": sma, "breadth_200": breadth, "vol_pct_20": vol}


def test_classify_each_state_and_unknown() -> None:
    assert regime.classify(_values(110, 100, 70, 30))[0] == "Calm trend"
    assert regime.classify(_values(90, 100, 20, 90))[0] == "High-vol down"
    assert regime.classify(_values(110, 100, 40, 30))[0] == "Choppy"  # narrow breadth
    assert regime.classify(_values(90, 100, 40, 50))[0] == "Choppy"  # below, calm vol
    assert regime.classify(_values(110, 100, 70, 85))[0] == "Choppy"  # above, high vol
    # Unknown volatility: High-vol down is false (above the average), but
    # Calm trend cannot be decided, so the state is unknown.
    state, results = regime.classify(_values(110, 100, 70, None))
    assert state is None and results[0][1] is False and results[1][1] is None
    # Kleene: a false clause decides even with another input unknown.
    assert regime.classify(_values(110, 100, None, 90))[0] == "Choppy"


def test_rules_are_written_as_shown() -> None:
    texts = {r.state: r.text() for r in regime.REGIME_RULES}
    assert texts == {
        "High-vol down": "index_close < index_sma_200 and vol_pct_20 >= 80",
        "Calm trend": "index_close > index_sma_200 and breadth_200 >= 50 and vol_pct_20 < 60",
        "Choppy": "otherwise",
    }
    words = " ".join(r.description for r in regime.REGIME_RULES).lower()
    assert not any(w in words for w in ("buy", "sell", "should"))


def _synthetic_index(kind: str) -> list[float]:
    rng = np.random.default_rng(7)
    n = 1400
    if kind == "calm":
        rets = rng.normal(0.0006, 0.01, n)
        rets[-60:] = rng.normal(0.0008, 0.003, 60)  # quiet lately
    else:
        rets = rng.normal(0.0004, 0.01, n)
        rets[-60:] = rng.normal(-0.006, 0.04, 60)  # a violent fall lately
    return list(100 * np.exp(np.cumsum(rets)))


def test_index_inputs_on_synthetic_series() -> None:
    calm = regime.index_inputs(_synthetic_index("calm"))
    assert calm["index_close"] > calm["index_sma_200"]  # pyright: ignore[reportOperatorIssue]
    assert calm["vol_pct_20"] is not None and calm["vol_pct_20"] < 20
    assert calm["vol_window"] == regime.VOL_WINDOW
    crash = regime.index_inputs(_synthetic_index("crash"))
    assert crash["index_close"] < crash["index_sma_200"]  # pyright: ignore[reportOperatorIssue]
    assert crash["vol_pct_20"] is not None and crash["vol_pct_20"] >= 95
    short = regime.index_inputs([100.0 + i for i in range(100)])
    assert short["index_sma_200"] is None and short["vol_pct_20"] is None


def test_regime_route_per_market(session, client) -> None:
    tickers = ["^GSPC", "AAA", "BBB", "CCC", "DDD"]
    _symbols(session, *tickers)
    _bars(session, "^GSPC", _synthetic_index("crash"), date(2019, 1, 1))
    for ticker in tickers[1:]:
        _bars(session, ticker, [100 - 0.1 * k for k in range(260)], date(2024, 1, 1))
    refresh_symbol_metrics(session)
    resp = client.get("/v1/regime")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=600"
    body = resp.json()
    us, india = body["markets"]
    assert us["market"] == "US" and us["index"] == "^GSPC" and us["index_name"] == "S&P 500"
    assert us["state"] == "High-vol down"
    assert us["breadth_universe"] == 4 and us["breadth_count"] == 0
    inputs = {i["name"]: i["value"] for i in us["inputs"]}
    assert inputs["breadth_200"] == 0 and inputs["vol_pct_20"] >= 80
    assert [r["state"] for r in us["rules"]] == ["High-vol down", "Calm trend", "Choppy"]
    assert us["rules"][0]["met"] is True
    assert india["market"] == "IN" and india["state"] is None
    assert india["reason"].startswith("Not enough data")
    assert "Not advice" in body["disclaimer"]
