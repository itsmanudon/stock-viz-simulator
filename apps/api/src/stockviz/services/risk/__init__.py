"""Portfolio risk (Phase 8): VaR, CVaR and Monte Carlo from stored history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session

from stockviz.models import Portfolio
from stockviz.services.risk.engine import (
    CONFIDENCES,
    HORIZONS,
    MonteCarloResult,
    VarResult,
    block_bootstrap,
    historical_var,
)
from stockviz.services.risk.scenarios import Scenarios, build_scenarios
from stockviz.services.trading.portfolio import PortfolioValuation


@dataclass(frozen=True, slots=True)
class RiskReport:
    scenarios: Scenarios
    var: list[VarResult]
    monte_carlo: MonteCarloResult | None


def compute_risk(
    session: Session, portfolio: Portfolio, valuation: PortfolioValuation, *, as_of: date
) -> RiskReport:
    scenarios = build_scenarios(session, portfolio, valuation, horizons=HORIZONS, as_of=as_of)
    if scenarios.reason is not None or scenarios.included == 0 or scenarios.nav_base <= 0:
        if scenarios.reason is None:
            scenarios.reason = "no holdings carry market risk"
        return RiskReport(scenarios, [], None)
    results = [
        result
        for horizon in HORIZONS
        for confidence in CONFIDENCES
        if (
            result := historical_var(
                list(scenarios.pnl[horizon]), confidence=confidence, horizon_days=horizon
            )
        )
        is not None
    ]
    daily = scenarios.pnl[1] / scenarios.nav_base
    mc = block_bootstrap(daily, start_value=scenarios.nav_base)
    return RiskReport(scenarios, results, mc)
