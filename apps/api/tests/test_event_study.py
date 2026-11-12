"""News event studies and index instruments (Phase 7.4).

A hand-built market with a known answer: the index never moves, each stock
is flat except for one jump on the first session that closed after its news
became available, so every abnormal return is known exactly.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    PriceBar,
    Symbol,
    TradeSide,
    User,
)
from stockviz.services.event_study import MIN_EVENTS, run_event_study
from stockviz.services.trading import ensure_default_portfolio, execute_trade
from stockviz.services.trading.execute import NotTradable

# 40 NYSE sessions with no holiday between them.
SESSIONS = [d.date() for d in pd.bdate_range("2025-07-07", periods=40)]
EVENT = 20  # the event bar's index


def _bars(session: Session, ticker: str, closes: list[float]) -> None:
    for day, close in zip(SESSIONS, closes, strict=True):
        c = Decimal(str(round(close, 6)))
        session.add(
            PriceBar(
                ticker=ticker, ts=datetime.combine(day, datetime.min.time()), interval="1d",
                open=c, high=c, low=c, close=c, volume=1000, source="test",
            )
        )  # fmt: skip


def _news(session: Session, ticker: str, available_at: datetime, label: str) -> None:
    doc = f"doc_{ticker}"
    session.add(
        AegisMapping(mapping_id=f"map_{ticker}", entity_id=f"ent_{ticker}", scheme="provider_id",
                     identifier=f"stockviz:{ticker}", created_at=datetime(2025, 1, 1))
    )  # fmt: skip
    session.add(
        AegisDocument(document_id=doc, source_id="s", source_name="Wire", title=f"{ticker} news",
                      url=None, published_at=None, first_seen_at=available_at,
                      available_at=available_at, last_signed_at=available_at)
    )  # fmt: skip
    session.flush()
    session.add(
        AegisDocumentEntity(document_id=doc, entity_id=f"ent_{ticker}", canonical_name=ticker,
                            kind="organization", resolution_analysis_id=f"r_{doc}", confidence=1.0)
    )  # fmt: skip
    session.add(
        AegisAnalysis(analysis_id=f"s_{doc}", document_id=doc, analysis_type="sentiment",
                      provider="p", model_name="m", model_version="1",
                      configuration_hash="0" * 64, available_at=available_at, label=label,
                      score=-0.5, outputs=[])
    )  # fmt: skip


def _market(session: Session, jumps: list[float], label: str = "negative") -> list[str]:
    """One stock per jump; news after the close of the session before EVENT."""
    session.add(Symbol(ticker="^GSPC", name="S&P 500 index"))
    tickers = [f"T{i:02d}" for i in range(len(jumps))]
    for t in tickers:
        session.add(Symbol(ticker=t, name=t))
    session.commit()
    _bars(session, "^GSPC", [100.0] * len(SESSIONS))
    # 22:00 UTC is after the 16:00 New York close (20:00 UTC in July).
    news_at = datetime.combine(SESSIONS[EVENT - 1], datetime.min.time()) + timedelta(hours=22)
    for t, jump in zip(tickers, jumps, strict=True):
        _bars(session, t, [50.0] * EVENT + [50.0 * (1 + jump)] * (len(SESSIONS) - EVENT))
        _news(session, t, news_at, label)
    session.commit()
    return tickers


def test_known_jumps_give_their_mean_and_spread(session: Session) -> None:
    jumps = [0.08, 0.12] * 6  # 12 events
    tickers = _market(session, jumps)
    study = run_event_study(session, tickers=tickers, sentiment="negative", pre=5, post=10)

    assert (study.events_found, study.events_used, study.events_incomplete) == (12, 12, 0)
    assert study.enough and study.benchmarks == dict.fromkeys(tickers, "^GSPC")
    assert {e.event_date for e in study.events} == {SESSIONS[EVENT]}

    logs = [math.log(1 + j) for j in jumps]
    mean = sum(logs) / 12
    se = math.sqrt(sum((x - mean) ** 2 for x in logs) / 11 / 12)
    by_window = {(w.start, w.end): w for w in study.windows}
    assert by_window[(0, 1)].mean_car == pytest.approx(mean)
    assert by_window[(0, 1)].std_error == pytest.approx(se)
    assert by_window[(0, 1)].t_stat == pytest.approx(mean / se)
    assert by_window[(-5, -1)].mean_car == pytest.approx(0.0)  # nothing before the news
    assert (0, 20) not in by_window  # longer than post=10
    path = {o: m for o, m, _se in study.path}
    assert path[-1] == pytest.approx(0.0) and path[0] == pytest.approx(mean)


def test_news_during_the_session_reacts_that_day(session: Session) -> None:
    tickers = _market(session, [0.1] * MIN_EVENTS)
    # Move every document to 15:00 UTC on the event day, before its close.
    from sqlmodel import select

    for doc in session.exec(select(AegisDocument)).all():
        doc.available_at = datetime.combine(SESSIONS[EVENT], datetime.min.time()) + timedelta(
            hours=15
        )
        session.add(doc)
    session.commit()
    study = run_event_study(session, tickers=tickers, sentiment="negative", pre=5, post=10)
    assert {e.event_date for e in study.events} == {SESSIONS[EVENT]}


def test_too_few_events_give_counts_not_figures(session: Session) -> None:
    tickers = _market(session, [0.1] * (MIN_EVENTS - 1))
    study = run_event_study(session, tickers=tickers, sentiment="negative", post=10)
    assert study.events_used == MIN_EVENTS - 1 and not study.enough
    assert study.windows == [] and study.path == []
    # A window past the stored bars is incomplete, not guessed.
    long = run_event_study(session, tickers=tickers, sentiment="negative", post=30)
    assert long.events_incomplete == MIN_EVENTS - 1 and long.events_used == 0
    # Another label matches nothing.
    assert run_event_study(session, tickers=tickers, sentiment="positive").events_found == 0


def test_an_index_cannot_be_traded(session: Session) -> None:
    session.add(Symbol(ticker="^GSPC", name="S&P 500 index"))
    session.commit()
    _bars(session, "^GSPC", [100.0] * len(SESSIONS))
    session.commit()
    user = User(email="ix@stockviz.dev", name="Ix")
    session.add(user)
    session.commit()
    assert user.id is not None
    ensure_default_portfolio(session, user.id)
    with pytest.raises(NotTradable):
        execute_trade(
            session, user_id=user.id, ticker="^GSPC", side=TradeSide.BUY, quantity=Decimal(1)
        )


def test_the_endpoint(session: Session, client: TestClient) -> None:
    tickers = _market(session, [0.05, 0.07] * 5)
    res = client.get(
        "/v1/research/event-study",
        params={"tickers": ",".join(tickers), "sentiment": "negative", "post": 10},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enough"] is True and body["events_used"] == 10
    w = next(w for w in body["windows"] if (w["start"], w["end"]) == (0, 1))
    expected = sum(math.log(1 + j) for j in [0.05, 0.07] * 5) / 10 * 100
    assert w["mean_car_pct"] == pytest.approx(expected, abs=1e-3)
    assert body["events"][0]["available_at"].startswith(SESSIONS[EVENT - 1].isoformat())
    assert client.get("/v1/research/event-study", params={"tickers": "NOPE"}).status_code == 404
    assert datetime.now(UTC)  # keep UTC import honest
