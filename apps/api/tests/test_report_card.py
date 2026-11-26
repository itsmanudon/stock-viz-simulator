"""A4.3 (M7.4): the report card, the trial ledger, PSR/DSR/PBO, plateaus, the
locked holdout, the Monte Carlo fan and the regime split.

The worked example (PSR, DSR, PBO) is ``docs/benchmarks/2026-11-26-a4-report-card.md``;
the numbers below are copied from it.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, select

from stockviz.models import BacktestTrial, HoldoutUnlock, PriceBar, User
from stockviz.schemas import BacktestIn
from stockviz.services.backtest import report, trials
from stockviz.services.backtest.regime_history import regime_history, states_on
from stockviz.services.backtest.report import Trip
from stockviz.services.backtest.walkforward import sweep, walk_forward
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
D0 = date(2024, 1, 1)

# --- the worked example -----------------------------------------------------

EXAMPLE = [0.010, -0.005, 0.007, 0.002, -0.012, 0.015, 0.004, -0.003, 0.009, 0.001]


def test_psr_matches_the_worked_example() -> None:
    mean, std, skew, kurt = report.moments(EXAMPLE)
    assert mean == pytest.approx(0.0028, abs=1e-12)
    assert std == pytest.approx(0.0079972217, abs=1e-9)
    assert skew == pytest.approx(-0.3239218, abs=1e-6)
    assert kurt == pytest.approx(2.3981439, abs=1e-6)
    sr = mean / std
    assert sr == pytest.approx(0.3501216, abs=1e-6)
    assert skew is not None and kurt is not None
    assert report.psr(sr, 0.0, len(EXAMPLE), skew, kurt) == pytest.approx(0.835670, abs=1e-6)


def test_dsr_matches_the_worked_example() -> None:
    mean, std, skew, kurt = report.moments(EXAMPLE)
    stats = report.SharpeStats(len(EXAMPLE), mean, std, mean / std, skew, kurt, None)
    assert report.expected_max_sharpe(5, 0.01) == pytest.approx(0.1192594, abs=1e-6)
    sr0, dsr = report.deflated(stats, 5, 0.01)
    assert sr0 == pytest.approx(0.1192594, abs=1e-6)
    assert dsr == pytest.approx(0.740241, abs=1e-6)
    # One trial: nothing to deflate, DSR = PSR(0).
    sr0, dsr1 = report.deflated(stats, 1, None)
    assert sr0 == 0.0
    assert skew is not None and kurt is not None
    assert dsr1 == pytest.approx(report.psr(mean / std, 0.0, 10, skew, kurt))


PBO_MATRIX = np.array(
    [
        [0.02, 0.004, -0.01],
        [0.01, -0.002, -0.02],
        [0.03, 0.003, -0.01],
        [0.01, -0.001, 0.00],
        [-0.02, 0.002, 0.01],
        [-0.01, -0.001, 0.02],
        [-0.02, 0.003, 0.03],
        [0.00, -0.002, 0.01],
    ]
)


def test_pbo_matches_the_worked_example() -> None:
    out = report.pbo_cscv(PBO_MATRIX, blocks=4, min_rows=2)
    assert out is not None
    assert out["combinations"] == 6 and out["block_sessions"] == 2 and out["dropped_sessions"] == 0
    expected = [
        math.log(1 / 3),  # blocks 1,2: A best in sample, worst out (rank 1)
        0.0,  # 1,3: B best, rank 2 of 3 (the median)
        0.0,  # 1,4: B, rank 2
        math.log(1 / 3),  # 2,3: C, rank 1
        math.log(0.375 / 0.625),  # 2,4: C, tied with A out of sample: rank 1.5
        math.log(1 / 3),  # 3,4: C, rank 1
    ]
    assert out["logits"] == pytest.approx(expected, abs=1e-9)
    assert out["pbo"] == 1.0


def test_pbo_is_low_when_the_in_sample_best_stays_best() -> None:
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 0.01, size=(320, 5))
    noise[:, 0] += 0.01  # one setting is genuinely better everywhere
    out = report.pbo_cscv(noise)
    assert out is not None and out["combinations"] == 12870
    assert out["pbo"] < 0.05
    assert report.pbo_cscv(noise[:10]) is None  # too few sessions


# --- metrics on a hand series ------------------------------------------------


def _curve(navs: list[float]) -> list[tuple[date, Decimal]]:
    return [(D0 + timedelta(days=i), Decimal(str(n))) for i, n in enumerate(navs)]


def test_metrics_on_a_hand_series() -> None:
    curve = _curve([100, 110, 99, 121])  # days 0..3, 3 calendar days
    trips = [
        Trip(D0, D0 + timedelta(days=1), Decimal(10), 2.0, False),
        Trip(D0 + timedelta(days=1), D0 + timedelta(days=2), Decimal(-5), -1.0, False),
        Trip(D0 + timedelta(days=2), D0 + timedelta(days=3), Decimal(20), None, False),
    ]
    m = {x["key"]: x for x in report.metrics(curve, trips, Decimal(100), max_drawdown=0.1)}
    years = 3 / 365.25
    assert m["cagr"]["value"] == pytest.approx(1.21 ** (1 / years) - 1)
    assert m["calmar"]["value"] == pytest.approx(m["cagr"]["value"] / 0.1)
    assert m["win_rate"]["value"] == pytest.approx(2 / 3)
    assert m["payoff_ratio"]["value"] == pytest.approx(15 / 5)
    assert m["profit_factor"]["value"] == pytest.approx(30 / 5)
    assert m["expectancy"]["value"] == pytest.approx(25 / 3)
    assert m["expectancy_r"]["value"] == pytest.approx(0.5)
    assert m["avg_holding_days"]["value"] == pytest.approx(1.0)
    assert m["exposure"]["value"] == pytest.approx(3 / 4)  # held at the close of days 0, 1, 2
    rf = 0.05 / 252
    e = [0.1 - rf, 99 / 110 - 1 - rf, 121 / 99 - 1 - rf]
    downside = math.sqrt(sum(min(x, 0) ** 2 for x in e) / 3)
    assert m["sortino"]["value"] == pytest.approx(sum(e) / 3 / downside * math.sqrt(252))
    assert all(x["formula"] for x in m.values())


def test_undefined_metrics_say_why() -> None:
    m = {x["key"]: x for x in report.metrics(_curve([100, 100]), [], Decimal(100), 0.0)}
    assert m["win_rate"]["value"] is None and m["win_rate"]["note"] == "No closed trades."
    assert m["calmar"]["value"] is None
    assert m["expectancy_r"]["value"] is None


# --- plateau -----------------------------------------------------------------


def test_plateau_flags_an_isolated_peak() -> None:
    flat = [(x, y, 1.0) for x in (1, 2, 3) for y in (1, 2, 3)]
    peak = [(x, y, 3.0 if (x, y) == (2, 2) else 0.2) for x in (1, 2, 3) for y in (1, 2, 3)]
    a = report.plateau(flat, x_param="a", y_param="b", metric="sharpe")
    b = report.plateau(peak, x_param="a", y_param="b", metric="sharpe")
    assert a is not None and not a["isolated"] and a["share_within"] == 1.0
    assert b is not None and b["isolated"] and b["within"] == 0 and b["neighbours"] == 8
    assert b["best"] == {"x": 2.0, "y": 2.0, "value": 3.0}


# --- Monte Carlo ---------------------------------------------------------------


def test_mc_fan_is_reproducible_by_seed() -> None:
    rng = random.Random(4)
    returns = [rng.gauss(0.0005, 0.01) for _ in range(300)]
    dates = [D0 + timedelta(days=i) for i in range(301)]
    a = report.mc_fan(returns, dates, 1000.0, seed=7)
    b = report.mc_fan(returns, dates, 1000.0, seed=7)
    c = report.mc_fan(returns, dates, 1000.0, seed=8)
    assert a == b and a is not None and c is not None
    assert a["max_drawdown"] != c["max_drawdown"]
    assert a["seed"] == 7 and a["horizon_days"] == 300
    assert a["max_drawdown"]["p5"] <= a["max_drawdown"]["p50"] <= a["max_drawdown"]["p95"]
    assert a["fan"][0]["p50"] == 1000.0 and a["fan"][-1]["date"] == dates[-1].isoformat()
    assert report.mc_fan(returns[:5], dates[:6], 1000.0) is None


# --- regime split ---------------------------------------------------------------


def _bars(session: Session, ticker: str, closes: list[float], start: date) -> None:
    day = start
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = Decimal(str(round(c, 4)))
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime.combine(day, datetime.min.time()),
                interval="1d",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
                source="test",
            )
        )
        day += timedelta(days=1)
    session.commit()


def _walk(seed: int, n: int, drift: float, vol: float, start: float = 100.0) -> list[float]:
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= 1 + rng.gauss(drift, vol)
        out.append(p)
    return out


def test_regime_history_uses_no_later_data(session: Session) -> None:
    members = [f"S{i}" for i in range(6)]
    seed_symbols(session, "^GSPC", *members)
    start = date(2015, 1, 1)
    _bars(session, "^GSPC", _walk(1, 900, 0.0004, 0.01), start)
    for k, t in enumerate(members):
        _bars(session, t, _walk(10 + k, 900, 0.0003, 0.015), start)
    a = regime_history(session, "S0", date(2016, 6, 1), date(2018, 6, 1))
    known = {d: s for d, s in a.states.items() if s is not None}
    assert known, a.reason
    cut = sorted(a.states)[len(a.states) // 2]
    # Rewrite every bar after the cut: no state up to the cut may change.
    for bar in session.exec(select(PriceBar).where(PriceBar.ts > datetime.combine(cut, datetime.min.time()))).all():  # fmt: skip
        bar.close = bar.close * Decimal("0.5")
        session.add(bar)
    session.commit()
    b = regime_history(session, "S0", date(2016, 6, 1), date(2018, 6, 1))
    assert {d: s for d, s in a.states.items() if d <= cut} == {
        d: s for d, s in b.states.items() if d <= cut
    }
    days = sorted(a.states)
    assert states_on(a, days) == [a.states[d] for d in days]


def test_regime_split_counts_a_day_under_the_previous_close_state() -> None:
    curve = _curve([100, 110, 121, 121])
    states = ["Calm trend", "Choppy", None, "Choppy"]
    rows = {r["state"]: r for r in report.regime_split(curve, states, [])}
    assert rows["Calm trend"]["sessions"] == 1 and rows["Calm trend"]["return"] == pytest.approx(
        0.1
    )
    assert rows["Choppy"]["return"] == pytest.approx(0.1)
    assert rows[None]["return"] == pytest.approx(0.0)


# --- ledger, holdout and the routes -------------------------------------------------


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="R")
    session.add(user)
    session.commit()
    assert user.id is not None
    return user.id


def _seed_aapl(session: Session, years: int = 6) -> None:
    seed_symbols(session, "AAPL")
    _bars(session, "AAPL", _walk(3, int(years * 261), 0.0003, 0.015), date(2018, 1, 1))


def _template(short: int = 10, long_: int = 50, **extra) -> dict:
    return {
        "ticker": "AAPL",
        "from": "2018-01-01",
        "to": "2023-12-31",
        "initial_cash": "10000",
        "strategy": {"type": "sma_crossover", "short_window": short, "long_window": long_},
        **extra,
    }


def test_unsaved_runs_are_recorded_and_variants_counted(
    client: TestClient, session: Session
) -> None:
    _seed_aapl(session)
    uid = _user(session, "t@example.com")
    first = client.post("/v1/backtest", json=_template(), headers=_headers(uid)).json()
    assert first["checks"]["trials"]["n"] == 1
    assert first["checks"]["dsr"]["value"] == pytest.approx(first["report"]["sharpe"]["psr"])
    client.post("/v1/backtest", json=_template(), headers=_headers(uid))  # a repeat
    third = client.post("/v1/backtest", json=_template(20, 100), headers=_headers(uid)).json()
    t = third["checks"]["trials"]
    assert t["n"] == 2 and t["runs"] == 3 and t["scope"] == "user"
    assert t["family_label"] == "SMA crossover · AAPL" and t["sharpe_variance"] is not None
    assert third["checks"]["dsr"]["n"] == 2
    # Anonymous runs land in the shared pool, keyed by nothing about the visitor.
    anon = client.post("/v1/backtest", json=_template(5, 50)).json()
    assert anon["checks"]["trials"]["scope"] == "anonymous" and anon["checks"]["trials"]["n"] == 1
    rows = session.exec(select(BacktestTrial)).all()
    assert len(rows) == 3 and {r.user_id for r in rows} == {uid, None}
    assert {r.source for r in rows} == {"run"}


def test_strategy_runs_share_a_family_across_numbers(client: TestClient, session: Session) -> None:
    _seed_aapl(session)
    uid = _user(session, "s@example.com")
    body = {
        "entry": {"rule": "close > sma(close, 50)"},
        "exit": {"rule": "close < sma(close, 50)"},
        "universe": {"ticker": "AAPL"},
        "from": "2019-01-01",
        "to": "2023-12-31",
        "initial_cash": "10000",
    }
    a = client.post("/v1/backtest/strategy", json=body, headers=_headers(uid)).json()
    body2 = {**body, "entry": {"rule": "close > sma(close, 20)"}}
    b = client.post("/v1/backtest/strategy", json=body2, headers=_headers(uid)).json()
    assert a["checks"]["trials"]["family_key"] == b["checks"]["trials"]["family_key"]
    assert b["checks"]["trials"]["n"] == 2
    assert {m["key"] for m in b["report"]["metrics"]} >= {"cagr", "expectancy_r", "exposure"}
    assert b["window"]["holdout"] == "last_20pct" and b["window"]["to_date"] < "2023-12-31"


def test_holdout_is_excluded_and_unlocked_once(client: TestClient, session: Session) -> None:
    _seed_aapl(session)
    uid = _user(session, "h@example.com")
    run = client.post("/v1/backtest", json=_template(), headers=_headers(uid)).json()
    w = run["window"]
    assert w["holdout"] == "last_20pct" and w["holdout_from"] > w["to_date"]
    assert run["equity_curve"][-1]["date"] <= w["to_date"]
    assert run["checks"]["holdout"]["status"] == "locked"
    assert run["checks"]["holdout"]["can_unlock"] is True

    anon = client.post("/v1/backtest/holdout/unlock", json={"backtest": _template()})
    assert anon.status_code == 401
    unlocked = client.post(
        "/v1/backtest/holdout/unlock", json={"backtest": _template()}, headers=_headers(uid)
    )
    assert unlocked.status_code == 200, unlocked.text
    seen = unlocked.json()["holdout"]
    assert seen["status"] == "seen" and seen["unlocked_at"] and seen["result"]
    assert seen["result"]["from_date"] == w["holdout_from"]
    again = client.post(
        "/v1/backtest/holdout/unlock", json={"backtest": _template()}, headers=_headers(uid)
    )
    assert again.status_code == 409
    # Every later run of the family (other numbers too) shows it as seen.
    later = client.post("/v1/backtest", json=_template(20, 100), headers=_headers(uid)).json()
    assert later["checks"]["holdout"]["status"] == "seen"
    assert len(session.exec(select(HoldoutUnlock)).all()) == 1
    # Explicitly off: the whole range, stamped.
    off = client.post("/v1/backtest", json=_template(holdout="none"), headers=_headers(uid)).json()
    assert off["window"]["holdout"] == "none" and off["checks"]["holdout"]["status"] == "none"
    assert off["equity_curve"][-1]["date"] > w["to_date"]
    nothing = client.post(
        "/v1/backtest/holdout/unlock",
        json={"backtest": _template(5, 100, holdout="none")},
        headers=_headers(uid),
    )
    assert nothing.status_code == 400


def test_sweeps_and_walk_forwards_never_see_the_holdout(session: Session) -> None:
    _seed_aapl(session)
    body = BacktestIn.model_validate(_template())
    before_s = sweep(session, body)
    before_w = walk_forward(session, body)
    hold_from = before_s.result["window"]["holdout_from"]
    assert before_w.result["windows"][-1]["out_of_sample_to"] < hold_from
    # Rewrite every held-out bar: neither study's data or result moves.
    for bar in session.exec(select(PriceBar)).all():
        if bar.ts.date().isoformat() >= hold_from:
            bar.close = bar.close * 2
            session.add(bar)
    session.commit()
    after_s = sweep(session, body)
    after_w = walk_forward(session, body)
    assert after_s.fingerprint == before_s.fingerprint and after_s.result == before_s.result
    assert after_w.fingerprint == before_w.fingerprint and after_w.result == before_w.result
    assert before_s.result["pbo"]["combinations"] == 12870
    assert before_s.result["plateau"]["sharpe"]["x_param"] == "short_window"


def test_sweep_members_are_trials_and_reruns_stay_identical(
    client: TestClient, session: Session
) -> None:
    _seed_aapl(session)
    uid = _user(session, "r@example.com")
    saved = client.post(
        "/v1/experiments/runs", json={"backtest": _template()}, headers=_headers(uid)
    ).json()
    assert saved["checks"]["trials"]["n"] == 1
    assert "checks" not in saved["result"] and saved["result"]["report"]
    swept = client.post(
        "/v1/experiments/sweep", json={"backtest": _template()}, headers=_headers(uid)
    )
    assert swept.status_code == 201, swept.text
    assert swept.json()["result"]["pbo"]["pbo"] >= 0
    # 15 sweep settings, one of them the saved run's numbers (a different
    # request hash: the sweep spec is not the same body).
    n = len({r.strategy_hash for r in session.exec(select(BacktestTrial)).all()})
    assert n >= 15
    got = client.get(f"/v1/experiments/runs/{saved['id']}", headers=_headers(uid)).json()
    assert got["checks"]["trials"]["n"] == n
    rerun = client.post(f"/v1/experiments/runs/{saved['id']}/rerun", headers=_headers(uid)).json()
    assert rerun["status"] == "identical", rerun


def test_old_requests_rerun_without_a_holdout() -> None:
    from stockviz.services.backtest.registry import as_saved

    assert as_saved({"adv_cap_pct": 10})["holdout"] == "none"
    assert as_saved({"adv_cap_pct": 10, "holdout": "last_20pct"})["holdout"] == "last_20pct"


def test_split_window_is_the_first_80_percent_of_calendar_days() -> None:
    w = trials.split_window(date(2020, 1, 1), date(2020, 1, 10), "last_20pct")
    assert w.to_date == date(2020, 1, 8) and w.holdout_from == date(2020, 1, 9)
    assert (
        trials.split_window(date(2020, 1, 1), date(2020, 1, 1), "last_20pct").holdout_from is None
    )
    assert trials.skeleton("sma(close, 50) > sma(close, 200) and rsi(14)[1] < 30.5") == (
        "sma(close, #) > sma(close, #) and rsi(#)[#] < #"
    )


def test_prune_trials_deletes_old_rows(session: Session) -> None:
    fam = trials.Family("k" * 64, "x", "template")
    stats = report.sharpe_stats([0.01, -0.01, 0.02])
    trials.record_trial(session, user_id=None, family=fam, source="run", strategy_hash="a" * 64,
                        fingerprint="f" * 64, label="x", stats=stats, total_return=0.0)  # fmt: skip
    row = session.exec(select(BacktestTrial)).one()
    row.last_run_at = row.last_run_at - timedelta(days=400)
    session.add(row)
    session.commit()
    assert trials.prune_trials(session, days=365) == 1
