"""A7.11 (M10.6): portfolio optimisation on seeded walks with known volatilities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar, SymbolMetrics
from stockviz.services import optimise as opt
from tests.symbols import seed_symbols

VOLS = {"LOW": 0.005, "MID": 0.01, "HIGH": 0.02, "WILD": 0.03}
DRIFT = {"LOW": 0.0002, "MID": 0.0004, "HIGH": 0.0008, "WILD": 0.0001}


def _frame(n: int = 700, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    common = rng.normal(size=n)
    data = {}
    for t, vol in VOLS.items():
        r = DRIFT[t] + vol * (0.4 * common + np.sqrt(1 - 0.16) * rng.normal(size=n))
        data[t] = 100 * np.exp(np.cumsum(r))
    index = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(data, index=index)


@pytest.fixture
def closes() -> pd.DataFrame:
    return _frame()


def _check(result: opt.Result, max_weight: float = 1.0) -> None:
    w = np.array(list(result.weights.values()))
    assert w.sum() == pytest.approx(1.0, abs=1e-6)
    assert (w >= 0).all() and (w <= max_weight + 1e-6).all()


def test_min_volatility_beats_equal_weight_and_favours_the_calm_symbol(closes) -> None:
    out = opt.optimise(closes, "USD", "min_volatility")
    _check(out)
    eq_vol = out.equal_weight["volatility"]
    assert out.volatility is not None and eq_vol is not None and out.volatility <= eq_vol
    assert max(out.weights, key=out.weights.__getitem__) == "LOW"


def test_hrp_gives_the_calmest_symbol_the_most_weight(closes) -> None:
    out = opt.optimise(closes, "USD", "hrp")
    _check(out)
    assert out.weights["LOW"] > out.weights["MID"] > out.weights["HIGH"] > out.weights["WILD"]


def test_max_sharpe_and_min_cvar_beat_equal_weight_on_their_own_measure(closes) -> None:
    sharpe = opt.optimise(closes, "USD", "max_sharpe", risk_free_rate=0.0)
    _check(sharpe)
    eq_sharpe = sharpe.equal_weight["sharpe"]
    assert sharpe.sharpe is not None and eq_sharpe is not None and sharpe.sharpe >= eq_sharpe
    cvar = opt.optimise(closes, "USD", "min_cvar", beta=0.95)
    _check(cvar)
    eq_cvar = cvar.equal_weight["cvar"]
    assert cvar.cvar is not None and eq_cvar is not None and cvar.cvar <= eq_cvar + 1e-9


def test_weight_cap_holds_and_an_impossible_cap_is_refused(closes) -> None:
    out = opt.optimise(closes, "USD", "min_volatility", max_weight=0.3)
    _check(out, 0.3)
    with pytest.raises(opt.OptimiseError, match="cannot reach 100%"):
        opt.optimise(closes, "USD", "hrp", max_weight=0.2)


def test_black_litterman_prior_and_a_view_moves_weight(closes) -> None:
    caps = {"LOW": 4e11, "MID": 3e11, "HIGH": 2e11, "WILD": 1e11}
    base = opt.optimise(closes, "USD", "black_litterman", market_caps=caps, risk_free_rate=0.0)
    _check(base)
    assert base.prior is not None and base.posterior == base.prior
    viewed = opt.optimise(
        closes,
        "USD",
        "black_litterman",
        market_caps=caps,
        risk_free_rate=0.0,
        views=[opt.View("WILD", 0.6, 0.9)],
    )
    assert viewed.posterior is not None and viewed.posterior["WILD"] > base.prior["WILD"]
    assert viewed.weights["WILD"] > base.weights["WILD"]
    with pytest.raises(opt.OptimiseError, match="no stored market cap for WILD"):
        opt.optimise(
            closes, "USD", "black_litterman", market_caps={"LOW": 1.0, "MID": 1.0, "HIGH": 1.0}
        )


def test_whole_shares_fit_the_cash(closes) -> None:
    out = opt.optimise(closes, "USD", "hrp", cash=100_000)
    spent = sum(out.allocation[t] * out.prices[t] for t in out.tickers)
    assert out.leftover is not None
    assert spent + out.leftover == pytest.approx(100_000, rel=1e-6)
    assert out.leftover < max(out.prices.values())
    assert all(isinstance(v, int) and v >= 0 for v in out.allocation.values())


def test_unknown_method_is_refused(closes) -> None:
    with pytest.raises(opt.OptimiseError, match="method must be"):
        opt.optimise(closes, "USD", "kelly")


def _store(session: Session, frame: pd.DataFrame, currency: str = "USD") -> None:
    seed_symbols(session, *frame.columns, currency=currency)
    for t in frame.columns:
        values = frame[t].to_numpy(dtype=float)
        for day, value in zip(frame.index, values, strict=True):
            ts = datetime.fromisoformat(str(day)[:10])
            price = Decimal(str(round(float(value), 4)))
            session.add(
                PriceBar(
                    ticker=t,
                    interval="1d",
                    ts=ts,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=1000,
                )
            )
    session.commit()


def test_route(client: TestClient, session: Session) -> None:
    _store(session, _frame(400))
    for t, cap in {"LOW": 4e11, "MID": 3e11, "HIGH": 2e11, "WILD": 1e11}.items():
        session.add(SymbolMetrics(ticker=t, market_cap_usd=cap, computed_at=datetime(2026, 1, 1)))
    session.commit()
    body = {
        "tickers": ["low", "MID", "HIGH", "WILD", "MID"],
        "method": "hrp",
        "years": 3,
        "cash": 50000,
    }
    out = client.post("/v1/research/optimise", json=body).json()
    assert [w["ticker"] for w in out["weights"]] == ["LOW", "MID", "HIGH", "WILD"]
    assert sum(w["weight"] for w in out["weights"]) == pytest.approx(1.0, abs=1e-6)
    assert out["sessions"] == 400 and out["currency"] == "USD" and out["leftover"] is not None
    assert all(w["shares"] is not None for w in out["weights"])
    assert (
        "not advice" in out["disclaimer"].lower()
        or "not a recommendation" in out["disclaimer"].lower()
    )

    bl = client.post(
        "/v1/research/optimise",
        json={
            **body,
            "method": "black_litterman",
            "views": [{"ticker": "WILD", "expected_return": 0.5, "confidence": 0.8}],
        },
    ).json()
    assert all(w["prior"] is not None and w["posterior"] is not None for w in bl["weights"])

    assert (
        client.post("/v1/research/optimise", json={**body, "tickers": ["LOW", "NOPE"]}).status_code
        == 404
    )
    one_year = client.post("/v1/research/optimise", json={**body, "years": 1}).json()
    assert 252 <= one_year["sessions"] < 400


def test_too_few_common_sessions_is_refused(session: Session) -> None:
    _store(session, pd.DataFrame(_frame(200)[["LOW", "MID"]]))
    with pytest.raises(opt.OptimiseError, match="needs 252 common sessions; 200"):
        opt.load_closes(session, ["LOW", "MID"], 3)


def test_mixed_currencies_are_refused(session: Session) -> None:
    _store(session, pd.DataFrame(_frame(300)[["LOW", "MID"]]))
    seed_symbols(session, "TCS.NS", currency="INR")
    with pytest.raises(opt.OptimiseError, match="different currencies"):
        opt.load_closes(session, ["LOW", "TCS.NS"], 3)
