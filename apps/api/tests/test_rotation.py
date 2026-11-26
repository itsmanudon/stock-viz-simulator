"""A4.4: cross-sectional rotation (top N by a numeric Rule DSL ranking)."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, User
from stockviz.services.backtest.rotation import (
    RotationSymbol,
    last_session_of_period,
    rebalance_signals,
    run_rotation,
)
from stockviz.services.markets.calendar import is_session
from stockviz.services.simulation import LEGACY_CLOSE, NEXT_OPEN
from stockviz.services.simulation.fees import NONE, US_EQUITY
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token


# --- the schedule ---------------------------------------------------------------


def test_weekly_signal_is_the_last_session_of_a_holiday_week() -> None:
    # Good Friday 2024-03-29: the week's last NYSE session is Thursday.
    assert last_session_of_period(date(2024, 3, 25), "weekly", "XNYS") == date(2024, 3, 28)
    assert last_session_of_period(date(2024, 4, 1), "weekly", "XNYS") == date(2024, 4, 5)


def test_monthly_signal_skips_month_end_weekends_and_holidays() -> None:
    # 31 Aug 2024 is a Saturday; 31 May 2021 is Memorial Day (a Monday).
    assert last_session_of_period(date(2024, 8, 5), "monthly", "XNYS") == date(2024, 8, 30)
    assert last_session_of_period(date(2021, 5, 3), "monthly", "XNYS") == date(2021, 5, 28)
    # NSE: whatever the holiday table says, the answer is the month's last session.
    last = last_session_of_period(date(2026, 3, 2), "monthly", "XNSE")
    assert last is not None and is_session(last, "XNSE") and last.month == 3
    assert all(not is_session(last + timedelta(days=k), "XNSE") for k in range(1, 32 - last.day))


def test_rebalance_signals_window_rules() -> None:
    signals = rebalance_signals(date(2024, 1, 1), date(2024, 4, 15), "monthly", "XNYS")
    # The session before the window, then each month that ended inside it; April is
    # still running on 15 April, so it does not rebalance.
    assert signals == [date(2023, 12, 29), date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 28)]
    weekly = rebalance_signals(date(2024, 3, 18), date(2024, 4, 3), "weekly", "XNYS")
    assert weekly == [date(2024, 3, 15), date(2024, 3, 22), date(2024, 3, 28)]


# --- the pure engine ------------------------------------------------------------


def _days(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _sym(ticker, days, closes, scores, *, first=0, vol=None) -> RotationSymbol:
    px = [Decimal(str(c)) for c in closes]
    return RotationSymbol(
        ticker=ticker, dates=days,
        ts=[datetime(d.year, d.month, d.day, 21, tzinfo=UTC) for d in days],
        open=px, high=px, low=px, close=px, volume=[Decimal(1_000_000)] * len(days),
        score=scores, first=first, vol=vol,
    )  # fmt: skip


def test_top_n_by_score_trades_on_the_next_bar_and_unknowns_are_not_ranked() -> None:
    days = _days(10)
    a = _sym("A", days, [10] * 10, [3.0] * 10)
    b = _sym("B", days, [20] * 10, [None] * 10)  # never ranked
    c = _sym("C", days, [40] * 10, [1.0] * 10)
    d = _sym("D", days, [50] * 10, [2.0] * 10)
    out = run_rotation(
        [a, b, c, d], signals=[days[0], days[5]], top_n=2, initial_cash=Decimal(10_000),
        schedule=NONE,
    )  # fmt: skip
    first = out.rebalances[0]
    assert [e.ticker for e in first.ranked] == ["A", "D", "C"]
    assert [u.ticker for u in first.unranked] == ["B"] and first.unranked[0].reason == "unknown"
    assert first.target == ["A", "D"] and first.trade_dates == [days[1]]
    assert first.weights == {"A": 0.5, "D": 0.5}
    held = {t.ticker: t for t in out.trades}
    assert set(held) == {"A", "D"} and all(t.open for t in out.trades)
    assert held["A"].quantity == 500 and held["D"].quantity == 100  # 5,000 each
    # Unchanged ranking: the second rebalance trades nothing.
    assert out.rebalances[1].entered == [] and out.rebalances[1].turnover == 0


def test_rank_changes_sell_leavers_and_buy_entrants_with_turnover() -> None:
    days = _days(12)
    a = _sym("A", days, [10] * 12, [3.0] * 6 + [0.5] * 6)
    c = _sym("C", days, [10] * 12, [1.0] * 12)
    d = _sym("D", days, [10] * 12, [2.0] * 12)
    out = run_rotation(
        [a, c, d], signals=[days[0], days[6]], top_n=2, initial_cash=Decimal(10_000),
        schedule=NONE,
    )  # fmt: skip
    second = out.rebalances[1]
    assert second.exited == ["A"] and second.entered == ["C"]
    assert second.trade_dates == [days[7]]
    # Sold 5,000 of A, bought 5,000 of C at 10: turnover (5,000 + 5,000) / 2 / 10,000.
    assert second.turnover == 0.5
    sold = next(t for t in out.trades if t.ticker == "A")
    assert sold.reason == "rebalance" and sold.exit_date == days[7] and not sold.open


def test_buffer_keeps_a_holding_inside_n_plus_buffer() -> None:
    days = _days(12)
    a = _sym("A", days, [10] * 12, [3.0] * 6 + [1.5] * 6)  # drops to rank 3
    c = _sym("C", days, [10] * 12, [1.0] * 12)
    d = _sym("D", days, [10] * 12, [2.0] * 12)
    e = _sym("E", days, [10] * 12, [0.1] * 6 + [2.5] * 6)
    kw = {"signals": [days[0], days[6]], "top_n": 2, "initial_cash": Decimal(10_000),
          "schedule": NONE}  # fmt: skip
    plain = run_rotation([a, c, d, e], **kw)  # type: ignore[arg-type]
    assert plain.rebalances[1].exited == ["A"]
    buffered = run_rotation([a, c, d, e], buffer=1, **kw)  # type: ignore[arg-type]
    assert buffered.rebalances[1].exited == [] and buffered.rebalances[1].target == ["D", "A"]


def test_cash_filter_moves_to_cash_and_back() -> None:
    days = _days(15)
    a = _sym("A", days, [10] * 15, [2.0] * 15)
    b = _sym("B", days, [10] * 15, [1.0] * 15)
    out = run_rotation(
        [a, b], signals=[days[0], days[5], days[10]],
        cash_filter={days[0]: False, days[5]: True, days[10]: None},
        top_n=1, initial_cash=Decimal(1_000), schedule=NONE,
    )  # fmt: skip
    r0, r1, r2 = out.rebalances
    assert r0.target == ["A"]
    assert r1.cash_filter is True and r1.target == [] and r1.exited == ["A"]
    assert r2.cash_filter is None and r2.target == ["A"]  # unknown does not act
    assert out.cash_filter_unknown == 1
    reasons = [t.reason for t in out.trades]
    assert reasons == ["cash_filter", "end_of_data"]
    nav = dict(out.equity_curve)
    assert nav[days[8]] == Decimal(1_000)


def test_costs_come_out_of_the_fills_and_net_is_below_gross() -> None:
    days = _days(12)
    a = _sym("A", days, [100] * 12, [3.0] * 6 + [0.5] * 6)
    b = _sym("B", days, [100] * 12, [1.0] * 12)
    out = run_rotation(
        [a, b], signals=[days[0], days[6]], top_n=1, initial_cash=Decimal(100_000),
        schedule=US_EQUITY, commission_bps=Decimal(10), profile=LEGACY_CLOSE,
    )  # fmt: skip
    assert out.total_fees > 0
    assert out.final_nav < Decimal(100_000) and out.gross_final_nav > out.final_nav
    sold = next(t for t in out.trades if t.ticker == "A")
    assert sold.pnl == -(sold.entry_fees + sold.exit_fees)


def test_inverse_volatility_weights_favour_the_calmer_name() -> None:
    days = _days(6)
    a = _sym("A", days, [10] * 6, [2.0] * 6, vol=[0.01] * 6)
    b = _sym("B", days, [10] * 6, [1.0] * 6, vol=[0.03] * 6)
    out = run_rotation(
        [a, b], signals=[days[0]], top_n=2, weighting="inverse_volatility",
        initial_cash=Decimal(10_000), schedule=NONE, profile=NEXT_OPEN,
    )  # fmt: skip
    w = out.rebalances[0].weights
    assert abs(w["A"] - 0.75) < 1e-9 and abs(w["B"] - 0.25) < 1e-9


# --- the route --------------------------------------------------------------------

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def _seed(session: Session, ticker: str, seed: int, n: int = 420) -> None:
    seed_symbols(session, ticker)
    rng = random.Random(seed)
    price = 100.0
    d = date(2022, 1, 3)
    k = 0
    while k < n:
        if d.weekday() < 5:
            open_ = price * (1 + rng.gauss(0, 0.005))
            price = open_ * (1 + rng.gauss(0.0005 * seed, 0.02))
            hi, lo = max(open_, price) * 1.005, min(open_, price) * 0.995
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime(d.year, d.month, d.day),
                    interval="1d",
                    open=Decimal(f"{open_:.4f}"),
                    high=Decimal(f"{hi:.4f}"),
                    low=Decimal(f"{lo:.4f}"),
                    close=Decimal(f"{price:.4f}"),
                    volume=2_000_000,
                    source="test",
                )
            )
            k += 1
        d += timedelta(days=1)
    session.commit()


def body(**over) -> dict:
    out = {
        "ranking": "pct_change(close, 20)",
        "top_n": 2,
        "schedule": "monthly",
        "universe": {"tickers": TICKERS},
        "from": "2022-06-01",
        "to": "2023-07-31",
        "initial_cash": "100000",
        "fee_schedule": "us_equity",
        "spread_bps": 5,
    }
    out.update(over)
    return out


def _seed_all(session: Session) -> None:
    for i, t in enumerate(TICKERS):
        _seed(session, t, seed=i + 1)


def test_rotation_route_shape(client: TestClient, session: Session) -> None:
    _seed_all(session)
    res = client.post("/v1/backtest/rotation", json=body())
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["mode"] == "rotation" and out["tickers"] == TICKERS
    assert out["rebalances"][0]["signal_date"] == "2022-05-31"
    assert out["equity_curve"][0]["date"] == "2022-06-01"
    for r in out["rebalances"]:
        assert len(r["held_after"]) <= 2
        assert all(d > r["signal_date"] for d in r["trade_dates"])
        assert [e["rank"] for e in r["ranked"]] == list(range(1, len(r["ranked"]) + 1))
    assert out["turnover"]["rebalances"] == len(out["rebalances"])
    assert out["report"]["metrics"] and out["checks"]["trials"]["n"] >= 1
    assert out["universe"]["survivorship_biased"] is True
    assert out["window"]["holdout"] == "last_20pct"
    assert Decimal(out["summary"]["gross_final_nav"]) >= Decimal(out["summary"]["final_nav"])
    again = client.post("/v1/backtest/rotation", json=body()).json()
    for key in ("rebalances", "trades", "equity_curve", "summary", "strategy_hash",
                "data_fingerprint"):  # fmt: skip
        assert again[key] == out[key]


def test_no_look_ahead_perturbing_bars_after_a_rebalance(client: TestClient, session: Session):
    _seed_all(session)
    before = client.post("/v1/backtest/rotation", json=body(holdout="none")).json()
    cut = datetime(2023, 3, 1)  # after the 2023-02-28 rebalance
    for bar in session.exec(select(PriceBar).where(col(PriceBar.ts) >= cut)).all():
        bar.open = bar.high = bar.low = bar.close = Decimal(7) if bar.ts.day % 2 else Decimal(700)
        session.add(bar)
    session.commit()
    after = client.post("/v1/backtest/rotation", json=body(holdout="none")).json()
    pick = lambda out: next(r for r in out["rebalances"] if r["signal_date"] == "2023-02-28")  # noqa: E731
    assert pick(before)["ranked"] == pick(after)["ranked"]
    assert pick(before)["held_after"] == pick(after)["held_after"]
    assert before["data_fingerprint"] != after["data_fingerprint"]


def test_ranking_must_be_a_number_and_rule_check_expects_one(
    client: TestClient, session: Session
) -> None:
    _seed_all(session)
    res = client.post("/v1/backtest/rotation", json=body(ranking="close > open"))
    assert res.status_code == 422 and "number" in res.json()["detail"]["message"]
    ok = client.post("/v1/rules/check", json={"rule": "pct_change(close, 126)", "expect": "number"})
    assert ok.json()["valid"] is True and ok.json()["type"] == "number series"
    cond = client.post("/v1/rules/check", json={"rule": "close > open", "expect": "number"})
    assert cond.json()["valid"] is False
    assert client.post("/v1/rules/check", json={"rule": "close > open"}).json()["valid"]
    one = client.post("/v1/backtest/rotation", json=body(universe={"tickers": ["AAA"]}))
    assert one.status_code == 400


def test_cash_filter_on_the_index(client: TestClient, session: Session) -> None:
    _seed_all(session)
    # No index bars: the filter is unknown at every rebalance and never acts.
    res = client.post(
        "/v1/backtest/rotation",
        json=body(cash_filter={"rule": "index_close < sma(index_close, 50)"}),
    ).json()
    assert res["cash_filter_index"] == "^GSPC"
    assert res["cash_filter_unknown"] == len(res["rebalances"])
    # A falling index: the filter is met and the run holds cash.
    seed_symbols(session, "^GSPC")
    d, k, price = date(2022, 1, 3), 0, 4000.0
    while k < 420:
        if d.weekday() < 5:
            price *= 0.998
            px = Decimal(f"{price:.2f}")
            session.add(PriceBar(ticker="^GSPC", ts=datetime(d.year, d.month, d.day),
                                 interval="1d", open=px, high=px, low=px, close=px,
                                 volume=0, source="test"))  # fmt: skip
            k += 1
        d += timedelta(days=1)
    session.commit()
    met = client.post(
        "/v1/backtest/rotation",
        json=body(cash_filter={"rule": "index_close < sma(index_close, 50)"}),
    ).json()
    assert all(r["cash_filter"] is True and r["held_after"] == [] for r in met["rebalances"])
    assert met["trades"] == []
    bad = client.post(
        "/v1/backtest/rotation", json=body(cash_filter={"rule": "fundamental.pe < 10"})
    )
    assert bad.status_code == 400


def test_saved_rotation_reruns_identical(client: TestClient, session: Session) -> None:
    _seed_all(session)
    row = User(email="a44@stockviz.dev", name="A44")
    session.add(row)
    session.commit()
    assert row.id is not None
    token = jose_jwt.encode({"sub": str(row.id)}, SECRET, algorithm="HS256")
    h = {"Authorization": f"Bearer {token}"}
    saved = client.post("/v1/experiments/runs", json={"rotation": body()}, headers=h)
    assert saved.status_code == 201, saved.text
    run = saved.json()
    assert run["kind"] == "rotation" and run["ticker"] == "AAA+5"
    assert run["checks"] is not None
    rerun = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=h).json()
    assert rerun["status"] == "identical", rerun
    bar = session.exec(
        select(PriceBar).where(PriceBar.ticker == "CCC", col(PriceBar.ts) >= datetime(2022, 7, 1))
    ).first()
    assert bar is not None
    bar.close = bar.close + Decimal(1)
    session.add(bar)
    session.commit()
    changed = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=h).json()
    assert changed["status"] == "data_changed"
    both = client.post("/v1/experiments/runs", json={"rotation": body(), "backtest": {}}, headers=h)
    assert both.status_code == 422
