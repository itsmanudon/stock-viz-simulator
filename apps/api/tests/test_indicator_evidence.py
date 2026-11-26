"""A3.4 (M2.6): evidence badges, the catalog's parameter schemas, parameter
bounds on the API and in rules, and the RS line on the indicators route."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz.models import IndicatorEvidence, PriceBar
from stockviz.services.checklist.evidence import study
from stockviz.services.dsl import RuleError, compile_rule, load_symbol
from stockviz.services.dsl import ast as dsl_ast
from stockviz.services.indicators import engine
from stockviz.services.indicators.evidence import (
    compiled_signals,
    latest_by_indicator,
    run_indicator_evidence,
)
from stockviz.services.indicators.signals import SIGNALS
from tests.symbols import seed_symbols

DAYS: list[date] = [d.date() for d in pd.bdate_range("2019-01-01", periods=900)]
TICKERS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
NOW = datetime(2026, 11, 27, 23, 0)


def _seed(session: Session, *, bench: bool = True) -> None:
    seed_symbols(session, *TICKERS, "^GSPC")
    for k, ticker in enumerate(TICKERS):
        rng = np.random.default_rng(10 + k)
        close = 50 * np.cumprod(1 + rng.normal(0.0003, 0.018, len(DAYS)))
        for i, day in enumerate(DAYS):
            c = float(close[i])
            hi, lo = c * (1 + abs(rng.normal(0, 0.006))), c * (1 - abs(rng.normal(0, 0.006)))
            o = float(np.clip(c * (1 + rng.normal(0, 0.004)), lo, hi))
            session.add(
                PriceBar(
                    ticker=ticker, ts=datetime.combine(day, time.min), interval="1d",
                    open=Decimal(f"{o:.4f}"), high=Decimal(f"{hi:.4f}"),
                    low=Decimal(f"{lo:.4f}"), close=Decimal(f"{c:.4f}"),
                    volume=int(rng.integers(1_000, 90_000)), source="test",
                )
            )  # fmt: skip
    if bench:
        for i, day in enumerate(DAYS):
            c = Decimal(f"{3000 + i:.2f}")
            session.add(
                PriceBar(
                    ticker="^GSPC", ts=datetime.combine(day, time.min), interval="1d",
                    open=c, high=c, low=c, close=c, volume=1, source="test",
                )
            )  # fmt: skip
    session.commit()


# --- signals -----------------------------------------------------------------


def test_every_signal_is_a_registry_study_on_its_default_parameters() -> None:
    for key, signal in SIGNALS.items():
        spec = engine.REGISTRY[key]
        rule = compile_rule(signal.rule)
        calls = [n for n in dsl_ast.walk(rule.canonical) if isinstance(n, dsl_ast.Call)]
        own = [c for c in calls if c.name == key]
        assert own, (key, "the signal must read its own study")
        if key not in ("sma", "ema"):  # the primitives on close take the series first
            for call in own:
                values = [a.value for a in call.args if isinstance(a, dsl_ast.Num)]
                assert values == [float(d) for d in spec.defaults], (key, values)
        # Neutral wording: a badge describes, it never advises.
        assert not re.search(r"\b(buy|sell|bullish|bearish)\b", signal.description, re.I), key


def test_studies_without_a_canonical_signal_have_none() -> None:
    for key in ("obv", "ad", "atr", "natr", "hv", "rvol", "pivots", "rsline", "rmv", "massi",
                "elder", "uo", "chop", "vwap", "wma"):  # fmt: skip
        assert key not in SIGNALS


# --- the study on the test universe --------------------------------------------


def test_run_grades_rsi_and_macd_on_the_test_universe(session: Session) -> None:
    _seed(session)
    end = DAYS[-1]
    run = run_indicator_evidence(session, end=end, now=NOW, only=["rsi", "macd"])
    rows = {r.indicator: r for r in session.exec(select(IndicatorEvidence)).all()}
    assert set(rows) == {"rsi", "macd"} and len(run.rows) == 2
    rules = compiled_signals(["rsi", "macd"])
    datasets = [load_symbol(session, t, end=end) for t in TICKERS]
    for key, row in rows.items():
        assert row.rule == rules[key].canonical_text and row.rule_hash == rules[key].hash
        assert row.universe == "pinned" and row.survivorship_biased and not row.point_in_time
        assert row.window_end == end and row.horizon == 20 and row.symbols == len(TICKERS)
        assert row.n_events > 0
        # The stored row is the A2.4 study itself, run on the same data.
        direct = study(datasets, rules[key], start=row.window_start, end=end)
        assert row.n_events == direct.n
        assert row.grade == direct.grade
        assert row.mean_excess == pytest.approx(direct.mean_excess)
        assert row.fee_schedules == {"us_equity": row.n_events}
    # Idempotent: a rerun replaces the rows.
    run_indicator_evidence(session, end=end, now=NOW, only=["rsi", "macd"])
    assert len(session.exec(select(IndicatorEvidence)).all()) == 2
    assert set(latest_by_indicator(session)) == {"rsi", "macd"}


def test_a_changed_rule_shows_no_old_grade(session: Session) -> None:
    session.add(
        IndicatorEvidence(
            indicator="rsi", rule="rsi(14) crosses_above 25", rule_hash="old", universe="pinned",
            point_in_time=False, survivorship_biased=True, window_start=DAYS[0],
            window_end=DAYS[-1], grade="A", n_events=99,
        )
    )  # fmt: skip
    session.commit()
    assert latest_by_indicator(session) == {}


# --- the catalog -----------------------------------------------------------------


def test_catalog_lists_parameters_and_badges(session: Session, client: TestClient) -> None:
    catalog = {c["key"]: c for c in client.get("/v1/indicators/catalog").json()}
    assert len(catalog) == len(engine.REGISTRY) >= 45
    rsi = catalog["rsi"]
    assert rsi["default_key"] == "rsi_14"
    assert rsi["parameters"] == [
        {"name": "n", "label": "n", "type": "int", "default": 14.0, "min": 1.0, "max": 500.0,
         "min_exclusive": False, "step": 1.0, "choices": []},
    ]  # fmt: skip
    psar = catalog["psar"]["parameters"]
    assert [p["type"] for p in psar] == ["float", "float"] and psar[0]["min_exclusive"]
    assert catalog["pivots"]["parameters"][0]["choices"] == ["bar", "week", "month", "year"]
    assert rsi["signal"]["rule"] == "rsi(14) crosses_above 30"
    assert rsi["signal"]["evidence"] is None  # before the job runs
    assert catalog["obv"]["signal"] is None and catalog["rsline"]["signal"] is None
    assert catalog["ichimoku"]["description"] and catalog["kama"]["source"]

    _seed(session)
    run_indicator_evidence(session, end=DAYS[-1], now=NOW, only=["rsi"])
    after = {c["key"]: c for c in client.get("/v1/indicators/catalog").json()}
    evidence = after["rsi"]["signal"]["evidence"]
    assert evidence["grade"] in ("A", "B", "C", "D", "insufficient")
    assert evidence["n_events"] > 0 and evidence["horizon"] == 20
    assert evidence["universe"]["survivorship_biased"] is True
    assert "survivorship" in evidence["universe"]["note"]
    assert after["macd"]["signal"]["evidence"] is None


# --- bounds on the route and in rules ---------------------------------------------


@pytest.mark.parametrize("names", ["rsi_0", "psar_0.02_2", "pivots_9", "kama_10_2_99"])
def test_out_of_bounds_parameters_are_400(session: Session, client: TestClient, names) -> None:
    seed_symbols(session, "AAA")
    response = client.get(f"/v1/symbols/AAA/indicators?names={names}")
    assert response.status_code == 400
    assert "must be" in response.json()["detail"]


def test_rules_use_the_registry_bounds() -> None:
    with pytest.raises(RuleError, match="max must be above 0 and at most 1"):
        compile_rule("psar(0.02, 2).direction > 0")
    with pytest.raises(RuleError, match="n must be a whole number from 1 to 250"):
        compile_rule("adx(300) > 20")
    assert compile_rule("psar(0.03, 0.3).direction > 0").lookback is not None


# --- the RS line on the route --------------------------------------------------------


def test_rs_line_reads_the_venue_index(session: Session, client: TestClient) -> None:
    _seed(session)
    body = client.get("/v1/symbols/AAA/indicators?names=rsline,psar,ichimoku&limit=30").json()
    assert body["meta"]["rsline"]["pane"] == "separate"
    points = body["series"]["rsline"]
    assert len(points) == 30
    bars = session.exec(
        select(PriceBar).where(PriceBar.ticker == "AAA").order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
    ).first()
    assert bars is not None
    bench_close = 3000 + len(DAYS) - 1
    assert points[-1]["value"] == pytest.approx(float(bars.close) / bench_close)
    assert set(body["series"]) >= {"psar.sar", "psar.direction", "ichimoku.senkou_a"}
    weekly = client.get("/v1/symbols/AAA/indicators?names=rsline&interval=1wk&limit=10").json()
    assert len(weekly["series"]["rsline"]) >= 9


def test_rs_line_is_missing_without_an_index(session: Session, client: TestClient) -> None:
    _seed(session, bench=False)
    body = client.get("/v1/symbols/AAA/indicators?names=rsline&limit=10").json()
    assert body["series"]["rsline"] == []
