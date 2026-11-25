"""A2's done-when: one rule, three consumers, one answer.

One rule text saved as a setup version must name the same symbols on the same
session date when it is read by

(a) a screen: ``GET /v1/screener?setup_version_id=`` as of that date;
(b) rule alerts armed before that date, firing when its bar arrives
    (``evaluate_pending_alerts``);
(c) the vector series a backtest reads: the symbols whose series turns true
    on that date (true there, not true on the bar before).

The rule is a crossing, so it is never true on two bars in a row: "met on
the date" (the screen) and "turned true on the date" (alerts, vector) are
the same set by construction, and any disagreement is a consumer bug.
Bars are seeded random walks, so the date is chosen where some symbols
cross and some do not.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, delete, select

from stockviz.models import Alert, AlertEvent, AlertKind, AlertRepeat, PriceBar, User
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.dsl import compile_rule
from stockviz.services.dsl.data import load_symbol
from stockviz.services.dsl.evaluate import vector
from stockviz.services.markets.calendar import is_session
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.setups import store
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

RULE = "close crosses_above sma(close, 10) and rsi(14) > 40"
TICKERS = ["AAPL", "MSFT", "KO", "PEP", "JNJ", "XOM", "CVX", "WMT"]
END = date(2025, 6, 10)  # a Tuesday, an XNYS session
SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


def _sessions(end: date, n: int) -> list[date]:
    out: list[date] = []
    day = end
    while len(out) < n:
        if is_session(day, "XNYS"):
            out.append(day)
        day -= timedelta(days=1)
    return out[::-1]


def _walks(days: list[date]) -> dict[str, list[PriceBar]]:
    rng = random.Random(20261126)
    out: dict[str, list[PriceBar]] = {}
    for ticker in TICKERS:
        close = 100.0
        bars: list[PriceBar] = []
        for day in days:
            close = max(5.0, close * (1 + rng.gauss(0, 0.02)))
            c = Decimal(str(round(close, 2)))
            bars.append(
                PriceBar(
                    ticker=ticker, ts=datetime(day.year, day.month, day.day), interval="1d",
                    open=c, high=c + 1, low=c - 1, close=c,
                    volume=1000 + rng.randint(0, 500), source="test",
                )
            )  # fmt: skip
        out[ticker] = bars
    return out


def _copy(bar: PriceBar) -> PriceBar:
    return PriceBar(**bar.model_dump(exclude={"id", "instrument_id"}))


def _turns_true(session: Session, ticker: str, day: date) -> bool:
    series = vector(compile_rule(RULE), load_symbol(session, ticker, end=day))
    ts = pd.Timestamp(day)
    position = series.index.get_loc(ts)
    assert isinstance(position, int)
    return _true(series.iloc[position]) and not _true(series.iloc[position - 1])


def _true(value: object) -> bool:
    """Kleene true: unknown (``pd.NA``) is not true."""
    return value is not pd.NA and bool(value)


def test_screen_alerts_and_vector_name_the_same_symbols(
    session: Session, client: TestClient
) -> None:
    seed_symbols(session, *TICKERS)
    days = _sessions(END, 160)
    walks = _walks(days)

    # Pick the session: the latest in the last 60 where some, not all, cross.
    for bars in walks.values():
        session.add_all([_copy(b) for b in bars])
    session.commit()
    target: date | None = None
    for day in reversed(days[-60:]):
        crossing = {t for t in TICKERS if _turns_true(session, t, day)}
        if 0 < len(crossing) < len(TICKERS):
            target = day
            break
    assert target is not None, "the seeded walks never split on one date"
    index = days.index(target)

    # Rewind to the session before the target.
    session.exec(
        delete(PriceBar).where(col(PriceBar.ts) >= datetime.combine(target, datetime.min.time()))
    )  # type: ignore[call-overload]
    session.commit()

    user = User(email="done-when@stockviz.dev", name="done-when")
    session.add(user)
    session.commit()
    assert user.id is not None
    _setup, version = store.create_setup(
        session, user.id, name="Cross", kind="alert", rule=compile_rule(RULE)
    )
    assert version.id is not None

    # (b) Alerts armed before the target date; the first pass records state.
    alerts: dict[int, str] = {}
    for ticker in TICKERS:
        alert = Alert(
            user_id=user.id, ticker=ticker, kind=AlertKind.RULE, setup_version_id=version.id,
            params={"setup_name": "Cross", "version": 1, "canonical": version.canonical_text},
            repeat=AlertRepeat.EVERY_CROSS, cooldown_sessions=1,
        )  # fmt: skip
        session.add(alert)
        session.commit()
        assert alert.id is not None
        alerts[alert.id] = ticker
    evaluate_pending_alerts(session)
    session.exec(delete(AlertEvent))  # type: ignore[call-overload]
    session.commit()

    # The target session's bar arrives.
    for ticker in TICKERS:
        session.add(_copy(walks[ticker][index]))
    session.commit()
    evaluate_pending_alerts(session)
    events = session.exec(select(AlertEvent)).all()
    assert {e.bar_date for e in events} <= {target}
    fired = {alerts[e.alert_id] for e in events}

    # (a) The screen of the same setup version as of the target date.
    refresh_symbol_metrics(session)
    session.commit()
    res = client.get(
        "/v1/screener",
        params={"setup_version_id": version.id, "as_of": target.isoformat(), "limit": 100},
        headers=_auth(user.id),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rule"]["sessions"]["XNYS"] == target.isoformat()
    assert body["rule"]["counts"]["unknown"] == 0
    screened = {row["ticker"] for row in body["rows"]}

    # (c) The vector series, as a backtest reads it.
    vectored = {t for t in TICKERS if _turns_true(session, t, target)}

    assert 0 < len(vectored) < len(TICKERS)
    assert screened == fired == vectored
