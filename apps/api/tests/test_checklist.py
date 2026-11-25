"""A2.4: the checklist dimensions, the nightly scores and the API."""

from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz import cli
from stockviz.models import ChecklistScore, PriceBar, Setup, SetupVersion
from stockviz.services.checklist.dimensions import (
    CHECKLIST_PRESETS,
    DIMENSIONS,
    SCOPE_INDIA,
    SCOPE_OTHER,
    VOLUME,
    aggregate,
    load_variants,
    scope_for,
    seed_dimensions,
)
from stockviz.services.checklist.score import run_checklist
from stockviz.services.dsl import compile_rule, vector
from stockviz.services.dsl.data import SymbolData, bars_frame
from tests.symbols import seed_symbols

NIGHT = datetime(2026, 11, 9, 22, 0)  # Monday, after the US close
LAST = date(2026, 11, 9)
BANNED = ("buy", "sell", "bullish", "bearish", "strong signal")


# --- definitions ----------------------------------------------------------------


def test_six_dimensions_each_compile_and_are_documented() -> None:
    assert [d.key for d in DIMENSIONS] == [
        "trend", "momentum", "volume", "regime", "quality", "risk",
    ]  # fmt: skip
    for d in DIMENSIONS:
        assert d.conditions and d.source and d.summary
        for scope in d.scopes:
            rule = compile_rule(d.rule_for(scope))
            assert rule.type.value == "boolean"
            for c in d.conditions_for(scope):
                compile_rule(c.rule)
    assert len(CHECKLIST_PRESETS) == 7  # Volume/Delivery has an India and an other setup
    assert all(p.kind == "checklist" for p in CHECKLIST_PRESETS)


def test_wording_is_neutral() -> None:
    texts = [d.name + d.summary + d.source for d in DIMENSIONS]
    texts += [c.label for d in DIMENSIONS for c in d.conditions]
    texts += [p.name + p.description for p in CHECKLIST_PRESETS]
    for text in texts:
        # A cited paper's title is quoted as published.
        lowered = text.lower().replace("returns to buying winners and selling losers", "")
        for word in BANNED:
            assert word not in lowered, (word, text)


def test_delivery_is_judged_only_on_indian_listings() -> None:
    assert scope_for("RELIANCE.NS", VOLUME) == SCOPE_INDIA
    assert scope_for("TCS.BO", VOLUME) == SCOPE_INDIA
    assert scope_for("AAPL", VOLUME) == SCOPE_OTHER
    assert "delivery_pct" in VOLUME.rule_for(SCOPE_INDIA)
    assert "delivery_pct" not in VOLUME.rule_for(SCOPE_OTHER)


def _tiny() -> SymbolData:
    rows = [(date(2026, 1, 1 + i), 10, 10, 10, 10, 100) for i in range(5)]
    return SymbolData("TINY", "XNYS", bars_frame(rows))


LITERAL = {"met": "close > 1", "not_met": "close < 1", "unknown": "fundamental.pe > 0"}


@pytest.mark.parametrize("statuses", list(itertools.product(LITERAL, repeat=3)))
def test_kleene_aggregation_equals_the_conjunction_rule(statuses: tuple[str, ...]) -> None:
    """A dimension's result (the setups' ``and``) equals ``aggregate`` of its conditions."""
    data = _tiny()
    rule = " and ".join(f"({LITERAL[s]})" for s in statuses)
    value = vector(rule, data).iloc[-1]
    got = "unknown" if value is pd.NA else ("met" if value else "not_met")
    assert got == aggregate(list(statuses))


def test_dimension_setups_are_versioned_system_setups(session: Session) -> None:
    first = seed_dimensions(session)
    assert set(first.values()) == {"created"}
    assert seed_dimensions(session) == dict.fromkeys(first, "unchanged")
    setups = session.exec(select(Setup).where(Setup.kind == "checklist")).all()
    assert len(setups) == 7
    assert all(s.is_preset and s.user_id is None for s in setups)
    variants = load_variants(session, seed=False)
    for (key, scope), v in variants.items():
        assert v.version.canonical_text == compile_rule(v.dimension.rule_for(scope)).canonical_text
        assert v.setup.preset_key == v.dimension.preset_key(scope)
        assert key == v.dimension.key
    assert len(session.exec(select(SetupVersion)).all()) == 7


def test_a_changed_formula_is_a_new_version(session: Session, monkeypatch) -> None:
    from dataclasses import replace

    from stockviz.services.checklist import dimensions

    seed_dimensions(session)
    old = load_variants(session, seed=False)[("risk", "all")].version
    changed = replace(dimensions.CHECKLIST_PRESETS[-1], rule="atr(14) < 0.05 * close")
    monkeypatch.setattr(
        dimensions, "CHECKLIST_PRESETS", (*dimensions.CHECKLIST_PRESETS[:-1], changed)
    )
    assert dimensions.seed_dimensions(session)[changed.key] == "new version"
    rows = session.exec(select(SetupVersion).where(SetupVersion.setup_id == old.setup_id)).all()
    assert sorted(r.version for r in rows) == [1, 2]


# --- nightly scores ---------------------------------------------------------------


def _bars(session: Session, ticker: str, end: date, n: int, *, base: float, step: float) -> None:
    days = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    for i, day in enumerate(days):
        c = Decimal(str(round(base + step * i, 4)))
        session.add(
            PriceBar(
                ticker=ticker, ts=day.to_pydatetime(), interval="1d",
                open=c, high=c, low=c, close=c, volume=1000 + 10 * i, source="test",
            )
        )  # fmt: skip
    session.commit()


def _world(session: Session) -> None:
    seed_symbols(session, "AAA", "BBB", "^GSPC")
    _bars(session, "AAA", LAST, 300, base=100, step=0.5)
    _bars(session, "BBB", date(2026, 11, 6), 300, base=100, step=0.5)  # missed Monday
    _bars(session, "^GSPC", LAST, 300, base=4000, step=1)


def _by_ticker(session: Session) -> dict[str, ChecklistScore]:
    from stockviz.services.instruments import instrument_ids

    ids = {v: k for k, v in instrument_ids(session, ["AAA", "BBB"]).items()}
    return {ids[r.instrument_id]: r for r in session.exec(select(ChecklistScore)).all()}


def test_nightly_scores_each_dimension_on_the_venue_session(session: Session) -> None:
    _world(session)
    run = run_checklist(session, now=NIGHT)
    assert run.symbols == 2  # the index is not scored
    assert run.sessions == {"XNYS": LAST}
    rows = _by_ticker(session)
    aaa = {d["key"]: d for d in rows["AAA"].dimensions}
    assert [d["key"] for d in rows["AAA"].dimensions] == [d.key for d in DIMENSIONS]
    assert aaa["trend"]["status"] == "met"
    assert aaa["regime"]["status"] == "met"  # the index rose above its 200-day
    assert aaa["volume"]["status"] == "met" and aaa["volume"]["scope"] == "other"
    assert aaa["risk"]["status"] == "met"
    # RSI(14) of a close that only rises is 100: above 70, so not met.
    assert aaa["momentum"]["status"] == "not_met"
    assert "RSI(14) at most 70" in aaa["momentum"]["reason"]
    assert aaa["quality"]["status"] == "unknown"
    assert "fundamental" in aaa["quality"]["reason"]
    assert (rows["AAA"].met_count, rows["AAA"].evaluated_count) == (4, 5)
    for d in rows["AAA"].dimensions:
        assert d["status"] == aggregate([c["status"] for c in d["conditions"]])
        assert d["setup_version_id"] is not None
    # A symbol without a bar on the venue's session is unknown, never judged stale.
    bbb = rows["BBB"]
    assert bbb.session_date == LAST and (bbb.met_count, bbb.evaluated_count) == (0, 0)
    assert all(d["reason"] == "no bar for 2026-11-09; latest 2026-11-06" for d in bbb.dimensions)


def test_the_job_is_idempotent(session: Session) -> None:
    _world(session)
    run_checklist(session, now=NIGHT)
    first = {t: (r.met_count, r.dimensions) for t, r in _by_ticker(session).items()}
    run_checklist(session, now=NIGHT)
    assert len(session.exec(select(ChecklistScore)).all()) == 2
    assert {t: (r.met_count, r.dimensions) for t, r in _by_ticker(session).items()} == first


def test_cli_checklist_is_a_recorded_job(engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    with Session(engine) as s:
        _world(s)
    from stockviz.services.checklist import score

    real = score.run_checklist
    monkeypatch.setattr(score, "run_checklist", lambda s: real(s, now=NIGHT))
    assert "checklist" in cli.RECORDED_JOBS and "checklist-evidence" in cli.RECORDED_JOBS
    assert "recommend" not in cli.RECORDED_JOBS
    assert cli.main(["checklist"]) == 0
    assert "checklist: 2 symbols (XNYS 2026-11-09)" in capsys.readouterr().out


# --- API ------------------------------------------------------------------------------


def test_checklist_api_shapes(session: Session, client: TestClient) -> None:
    _world(session)
    run_checklist(session, now=NIGHT)
    body = client.get("/v1/checklist").json()
    assert [d["key"] for d in body["dimensions"]] == [d.key for d in DIMENSIONS]
    volume = next(d for d in body["dimensions"] if d["key"] == "volume")
    assert [v["scope"] for v in volume["variants"]] == ["india", "other"]
    trend = body["dimensions"][0]["variants"][0]
    assert trend["canonical"] and len(trend["hash"]) == 64 and trend["version"] == 1
    assert [c["label"] for c in trend["conditions"]] == [
        "Close above the 200-day average", "50-day average above the 200-day",
    ]  # fmt: skip
    assert trend["evidence"] is None  # no study yet
    assert body["universe"]["survivorship_biased"] is True
    assert "not a recommendation" in body["disclaimer"]
    assert body["total"] == 2
    first = body["rows"][0]
    assert first["ticker"] == "AAA" and first["met"] == 4 and first["total"] == 6
    assert first["evaluated"] == 5 and first["stale"] is False
    assert {r["status"] for r in first["results"]} == {"met", "not_met", "unknown"}
    assert first["results"][0]["conditions"][0]["rule"]

    assert [r["ticker"] for r in client.get("/v1/checklist?min_met=1").json()["rows"]] == ["AAA"]
    assert client.get("/v1/checklist?dimension=momentum").json()["total"] == 0
    assert client.get("/v1/checklist?dimension=trend").json()["total"] == 1
    assert client.get("/v1/checklist?dimension=nope").status_code == 400
    assert [r["ticker"] for r in client.get("/v1/checklist?sort=ticker").json()["rows"]] == [
        "AAA", "BBB",
    ]  # fmt: skip


def test_symbol_checklist(session: Session, client: TestClient) -> None:
    _world(session)
    assert client.get("/v1/symbols/AAA/checklist").json()["row"] is None  # seeded on read
    run_checklist(session, now=NIGHT)
    body = client.get("/v1/symbols/aaa/checklist").json()
    assert body["ticker"] == "AAA" and body["row"]["met"] == 4
    assert body["row"]["session_date"] == "2026-11-09"
    assert len(body["dimensions"]) == 6
    assert client.get("/v1/symbols/NOPE/checklist").status_code == 404
    assert client.get("/v1/symbols/%5EGSPC/checklist").status_code == 404


def test_grades_show_with_their_sample(session: Session, client: TestClient) -> None:
    from stockviz.models import ChecklistEvidence

    _world(session)
    variants = load_variants(session)
    version = variants[("trend", "all")].version
    session.add(
        ChecklistEvidence(
            setup_version_id=version.id or 0, dimension="trend", scope="all", universe="pinned",
            point_in_time=False, survivorship_biased=True, window_start=date(2016, 11, 9),
            window_end=LAST, horizon=20, symbols=25, n_events=120, mean_excess=0.012,
            t_stat=3.4, hit_rate=0.58, grade="A", fee_schedules={"us_equity_2026": 120},
        )
    )  # fmt: skip
    session.commit()
    trend = client.get("/v1/checklist").json()["dimensions"][0]["variants"][0]
    assert trend["evidence"]["grade"] == "A"
    assert trend["evidence"]["n_events"] == 120
    assert trend["evidence"]["universe"]["survivorship_biased"] is True
    assert "survivorship" in trend["evidence"]["universe"]["note"]


def test_recommendations_endpoint_is_gone(client: TestClient) -> None:
    assert client.get("/v1/recommendations").status_code == 404


# --- index_close (A2.4 binding) ---------------------------------------------------------


def test_index_close_reads_the_venue_index_point_in_time() -> None:
    rows = [(date(2026, 1, 5) + timedelta(days=i), 10, 10, 10, 10, 100) for i in range(10)]
    bars = bars_frame(rows)
    bench = pd.Series(np.arange(10, dtype=float) + 100, index=bars.index, dtype=float).iloc[
        [0, 1, 2, 3, 5, 6, 7, 8, 9]
    ]  # a missing index day is forward-filled
    data = SymbolData("ZZZ", "XNYS", bars, benchmark=bench, benchmark_ticker="^GSPC")
    rule = compile_rule("index_close > 103", require_condition=False)
    assert rule.needs.benchmark is True
    values = vector("index_close", data).to_numpy()
    assert values[4] == 103  # forward-filled from the day before
    assert values[9] == 109
    assert list(vector(rule, data))[3:6] == [False, False, True]

    from stockviz.services.dsl import evaluate_at

    bare = SymbolData("ZZZ", "XNYS", bars)
    outcome, _ = evaluate_at(rule, bare, bare.dates[-1])
    assert outcome.status == "unknown"
    assert outcome.reasons[0] == "index_close: no index series for ZZZ's venue"


def test_conformance_corpus_holds_every_checklist_rule() -> None:
    from tests.test_dsl_conformance import CORPUS

    for d in DIMENSIONS:
        for scope in d.scopes:
            assert d.rule_for(scope) in CORPUS
    assert any("index_close" in r for r in CORPUS)
