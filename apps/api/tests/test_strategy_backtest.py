"""A4.1: POST /v1/backtest/strategy and the experiment registry's strategy runs."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz.models import ExperimentRun, PriceBar, User
from stockviz.models.setup import Setup, SetupVersion
from stockviz.models.watchlist import Watchlist, WatchlistItem
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token
ENTRY = "close crosses_above sma(close, 10)"
EXIT = "close crosses_below sma(close, 10)"


def headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def user(session: Session, email: str = "a41@stockviz.dev") -> int:
    row = User(email=email, name="A41")
    session.add(row)
    session.commit()
    assert row.id is not None
    return row.id


def weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def seed_walk(session: Session, ticker: str, *, seed: int, n: int = 300, currency: str = "USD"):
    seed_symbols(session, ticker, currency=currency)
    rng = random.Random(seed)
    price = 100.0
    for day in weekdays(date(2023, 1, 2), n):
        open_ = price * (1 + rng.gauss(0, 0.01))
        close = open_ * (1 + rng.gauss(0, 0.02))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.01)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.01)))
        price = close
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime(day.year, day.month, day.day),
                interval="1d",
                open=Decimal(f"{open_:.4f}"),
                high=Decimal(f"{high:.4f}"),
                low=Decimal(f"{low:.4f}"),
                close=Decimal(f"{close:.4f}"),
                volume=1_000_000,
                source="test",
            )
        )
    session.commit()


def body(**over) -> dict:
    out = {
        "entry": {"rule": ENTRY},
        "exit": {"rule": EXIT},
        "stops": {"atr": {"multiple": 2, "period": 14}},
        "sizing": {"kind": "fixed_risk", "risk_pct": 1},
        "universe": {"ticker": "AAPL"},
        "from": "2023-06-01",
        "to": "2024-02-28",
        "initial_cash": "100000",
        "fee_schedule": "us_equity_2026",
        "spread_bps": 5,
    }
    out.update(over)
    return out


def test_strategy_run_shape(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    res = client.post("/v1/backtest/strategy", json=body())
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["mode"] == "strategy" and out["tickers"] == ["AAPL"]
    assert out["execution_profile"] == "next_open/v1"
    assert out["warmup_bars"] > 0
    assert out["equity_curve"][0]["date"] >= "2023-06-01"
    assert out["trades"], "the walk crosses its SMA"
    for t in out["trades"]:
        assert t["reason"] in {"exit_rule", "stop_atr", "end_of_data"}
        assert t["initial_risk"] is not None and t["r_multiple"] is not None
        assert Decimal(t["quantity"]) == Decimal(t["quantity"]).to_integral_value()
    assert [r["role"] for r in out["rules"]] == ["entry", "exit"]
    assert out["universe"]["survivorship_biased"] is True
    assert out["benchmark"]["kind"] == "buy_and_hold"
    s = out["summary"]
    assert Decimal(s["gross_final_nav"]) >= Decimal(s["final_nav"])
    assert len(out["strategy_hash"]) == 64 and len(out["data_fingerprint"]) == 64


def test_inline_and_version_give_the_same_hash(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    a = client.post("/v1/backtest/strategy", json=body(entry={"rule": "close  >  sma(close,10)"}))
    b = client.post("/v1/backtest/strategy", json=body(entry={"rule": "close > sma(close, 10)"}))
    assert a.json()["strategy_hash"] == b.json()["strategy_hash"]


def test_no_look_ahead_perturbing_later_bars(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=3)
    cut = datetime(2023, 11, 1)
    before = client.post("/v1/backtest/strategy", json=body()).json()
    for bar in session.exec(select(PriceBar).where(col(PriceBar.ts) >= cut)).all():
        bar.open = bar.high = bar.low = bar.close = Decimal("5") if bar.ts.day % 2 else Decimal(500)
        session.add(bar)
    session.commit()
    after = client.post("/v1/backtest/strategy", json=body()).json()
    early = lambda out: [t for t in out["trades"] if t["exit_date"] < "2023-11-01"]  # noqa: E731
    assert early(before) and early(before) == early(after)
    assert [p for p in before["equity_curve"] if p["date"] < "2023-11-01"] == [
        p for p in after["equity_curve"] if p["date"] < "2023-11-01"
    ]
    assert before["data_fingerprint"] != after["data_fingerprint"]


def test_unknown_signals_are_counted(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    out = client.post(
        "/v1/backtest/strategy",
        json=body(entry={"rule": "fundamental.pe < 30"}, exit=None, stops={}, sizing={}),
    ).json()
    assert (
        out["trades"] == [] and out["unknown_entry_bars"] == len(out["equity_curve"]) - 1
    )  # the last bar never acts


def test_basket_max_positions_and_benchmark(client: TestClient, session: Session) -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "META"]
    for i, t in enumerate(tickers):
        seed_walk(session, t, seed=10 + i)
    out = client.post(
        "/v1/backtest/strategy",
        json=body(universe={"tickers": tickers}, sizing={"kind": "all_in", "max_positions": 2}),
    ).json()
    assert out["benchmark"]["kind"] == "equal_weight_buy_and_hold"
    assert len(out["symbols"]) == 5
    # Never more than two open at once.
    spans = [(t["entry_date"], t["exit_date"]) for t in out["trades"]]
    for day in {d for span in spans for d in span}:
        assert sum(1 for a, b in spans if a <= day < b) <= 2


def test_basket_must_be_one_currency(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    seed_walk(session, "TCS.NS", seed=2, currency="INR")
    res = client.post("/v1/backtest/strategy", json=body(universe={"tickers": ["AAPL", "TCS.NS"]},
                                                          fee_schedule="none"))  # fmt: skip
    assert res.status_code == 400 and "one currency" in res.json()["detail"]


def test_shorts_refused_unless_declared_and_us(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    seed_walk(session, "TCS.NS", seed=2, currency="INR")
    res = client.post("/v1/backtest/strategy", json=body(direction="short"))
    assert res.status_code == 400 and "not declared shortable" in res.json()["detail"]
    res = client.post(
        "/v1/backtest/strategy",
        json=body(direction="short", shortable=["TCS.NS"], universe={"ticker": "TCS.NS"},
                  fee_schedule="in_delivery_nse_2026"),
    )  # fmt: skip
    assert res.status_code == 400 and "US only" in res.json()["detail"]
    res = client.post("/v1/backtest/strategy", json=body(direction="short", shortable=["aapl"]))
    assert res.status_code == 200, res.text
    assert all(t["direction"] == "short" for t in res.json()["trades"])


def test_bad_rule_is_422_and_unknown_symbol_404(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    res = client.post("/v1/backtest/strategy", json=body(entry={"rule": "close >"}))
    assert res.status_code == 422 and res.json()["detail"]["kind"]
    res = client.post("/v1/backtest/strategy", json=body(universe={"ticker": "NOPE"}))
    assert res.status_code == 404


def test_watchlist_universe_needs_its_owner(client: TestClient, session: Session) -> None:
    seed_walk(session, "AAPL", seed=1)
    seed_walk(session, "MSFT", seed=2)
    owner, other = user(session), user(session, "other@stockviz.dev")
    wl = Watchlist(user_id=owner, name="Tech")
    session.add(wl)
    session.commit()
    for t in ("MSFT", "AAPL"):
        session.add(WatchlistItem(watchlist_id=wl.id, ticker=t))  # type: ignore[arg-type]
    session.commit()
    req = body(universe={"watchlist_id": wl.id})
    assert client.post("/v1/backtest/strategy", json=req).status_code == 401
    assert client.post("/v1/backtest/strategy", json=req, headers=headers(other)).status_code == 404
    res = client.post("/v1/backtest/strategy", json=req, headers=headers(owner))
    assert res.status_code == 200
    assert res.json()["source"] == {"kind": "watchlist", "watchlist_id": wl.id, "name": "Tech",
                                    "tickers": ["MSFT", "AAPL"]}  # fmt: skip


def test_saved_strategy_reruns_identical(client: TestClient, session: Session) -> None:
    """The design note's acceptance: entry, exit, an ATR stop and fixed-risk
    sizing rerun ``identical`` from the experiment registry."""
    seed_walk(session, "AAPL", seed=1)
    uid = user(session)
    res = client.post("/v1/experiments/runs", json={"strategy": body()}, headers=headers(uid))
    assert res.status_code == 201, res.text
    run = res.json()
    assert run["kind"] == "strategy" and run["ticker"] == "AAPL"
    # Inline rules became versions of the user's setup; the request names them.
    assert set(run["request"]["entry"]) == {"setup_version_id", "rule"}
    assert run["request"]["entry"]["rule"] is None
    setup = session.exec(select(Setup).where(col(Setup.user_id) == uid)).one()
    assert setup.kind == "strategy"
    versions = session.exec(
        select(SetupVersion).where(col(SetupVersion.setup_id) == setup.id)
    ).all()
    assert len(versions) == 2
    row = session.get(ExperimentRun, run["id"])
    assert row is not None and row.setup_version_id == run["request"]["entry"]["setup_version_id"]
    # Same result as the public endpoint, apart from the version ids.
    public = client.post("/v1/backtest/strategy", json=body()).json()
    assert run["result"]["trades"] == public["trades"]
    assert run["result"]["strategy_hash"] == public["strategy_hash"]

    rerun = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers(uid)).json()
    assert rerun["status"] == "identical", rerun

    # Saving again reuses the versions.
    client.post("/v1/experiments/runs", json={"strategy": body()}, headers=headers(uid))
    assert len(session.exec(select(SetupVersion)).all()) == 2

    # A4.3: the last bar is in the held-out 20%, which the run never read.
    bar = session.exec(select(PriceBar).order_by(col(PriceBar.ts).desc())).first()
    assert bar is not None
    bar.close = bar.close + 1
    session.add(bar)
    session.commit()
    rerun = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers(uid)).json()
    assert rerun["status"] == "identical"
    bar = session.exec(
        select(PriceBar)
        .where(col(PriceBar.ts) < datetime(2023, 12, 1))
        .order_by(col(PriceBar.ts).desc())
    ).first()
    assert bar is not None
    bar.close = bar.close + 1
    session.add(bar)
    session.commit()
    rerun = client.post(f"/v1/experiments/runs/{run['id']}/rerun", headers=headers(uid)).json()
    assert rerun["status"] == "data_changed"


def test_run_body_takes_one_of_backtest_or_strategy(client: TestClient, session: Session) -> None:
    uid = user(session)
    res = client.post("/v1/experiments/runs", json={}, headers=headers(uid))
    assert res.status_code == 422
