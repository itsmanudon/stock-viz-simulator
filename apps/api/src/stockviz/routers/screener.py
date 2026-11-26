"""Screening the universe (Phase 6.2).

- ``GET /v1/screener``: the unified screener. Market (country), exchange
  (MIC) and currency filters for both markets, technical filters from the
  nightly snapshot, server-side sort and offset paging with a total.
- A2.2: ``rule=`` (Rule DSL text) or ``setup_version_id=`` (a preset's, or
  your own with a Bearer token) refines the filters: the rule is judged on
  every candidate at its venue's latest completed session (or ``as_of``),
  then rows are sorted and paged. ``rule_mode=met_only`` (default) keeps the
  met rows; ``all`` keeps every row with ``rule_result`` and, when unknown,
  ``rule_reason``. Every page carries the universe stamp.
- ``GET /v1/symbols/screen``: the original list endpoint, kept for its
  callers (screener-era pages, the landing page's proofs). Same query path,
  so momentum is now applied before the limit too (audit RS-5).

Filters read the precomputed ``symbol_metrics`` snapshot rather than
rescanning ``price_bars``; see ``services/screener.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session

from stockviz.auth import OptionalUserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import (
    RULE_MAX_LENGTH,
    ScreenerPageOut,
    ScreenerResultOut,
    ScreenerRowOut,
    ScreenerRuleCountsOut,
    ScreenerRuleOut,
)
from stockviz.services.backtest.universe import screen_universe
from stockviz.services.screener import (
    MAX_MOMENTUM_DAYS,
    NEAR_52W_THRESHOLD,  # noqa: F401  (re-exported for older imports)
    SORT_KEYS,
    ScreenQuery,
    run_screen,
    run_screen_full,
)
from stockviz.services.setups import store as setups
from stockviz.services.setups.rules import compile_or_422

router = APIRouter(prefix="/v1/symbols", tags=["screener"])
page_router = APIRouter(prefix="/v1", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_RESULTS = 200
MAX_PAGE = 100


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@page_router.get("/screener", response_model=ScreenerPageOut)
@limiter.limit("30/minute")
def screener(
    request: Request,
    session: SessionDep,
    market: Annotated[str | None, Query(description="Countries, e.g. US,IN")] = None,
    exchange: Annotated[str | None, Query(description="MICs, e.g. XNAS,XNSE")] = None,
    currency: Annotated[str | None, Query(description="e.g. USD,INR")] = None,
    sector: Annotated[str | None, Query()] = None,
    rsi_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    rsi_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    momentum_days: Annotated[int | None, Query(ge=1, le=MAX_MOMENTUM_DAYS)] = None,
    momentum_min: Annotated[float | None, Query()] = None,
    momentum_max: Annotated[float | None, Query()] = None,
    near_52w_high: Annotated[bool, Query()] = False,
    near_52w_low: Annotated[bool, Query()] = False,
    above_sma_50: Annotated[bool | None, Query()] = None,
    above_sma_200: Annotated[bool | None, Query()] = None,
    hv_min: Annotated[float | None, Query(ge=0)] = None,
    hv_max: Annotated[float | None, Query(ge=0)] = None,
    atr_pct_min: Annotated[float | None, Query(ge=0)] = None,
    atr_pct_max: Annotated[float | None, Query(ge=0)] = None,
    sentiment_min: Annotated[float | None, Query(ge=-1, le=1)] = None,
    sentiment_max: Annotated[float | None, Query(ge=-1, le=1)] = None,
    pe_min: Annotated[float | None, Query()] = None,
    pe_max: Annotated[float | None, Query()] = None,
    pb_min: Annotated[float | None, Query()] = None,
    pb_max: Annotated[float | None, Query()] = None,
    ps_min: Annotated[float | None, Query()] = None,
    ps_max: Annotated[float | None, Query()] = None,
    ev_ebitda_min: Annotated[float | None, Query()] = None,
    ev_ebitda_max: Annotated[float | None, Query()] = None,
    dividend_yield_min: Annotated[float | None, Query()] = None,
    dividend_yield_max: Annotated[float | None, Query()] = None,
    market_cap_usd_min: Annotated[float | None, Query()] = None,
    market_cap_usd_max: Annotated[float | None, Query()] = None,
    net_margin_min: Annotated[float | None, Query()] = None,
    net_margin_max: Annotated[float | None, Query()] = None,
    roe_min: Annotated[float | None, Query()] = None,
    roe_max: Annotated[float | None, Query()] = None,
    debt_to_equity_min: Annotated[float | None, Query()] = None,
    debt_to_equity_max: Annotated[float | None, Query()] = None,
    revenue_growth_min: Annotated[float | None, Query()] = None,
    revenue_growth_max: Annotated[float | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^(" + "|".join(SORT_KEYS) + ")$")] = "ticker",
    dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    rule: Annotated[
        str | None,
        Query(max_length=RULE_MAX_LENGTH, description="A Rule DSL condition"),
    ] = None,
    setup_version_id: Annotated[int | None, Query(ge=1)] = None,
    rule_mode: Annotated[Literal["met_only", "all"], Query()] = "met_only",
    as_of: Annotated[date | None, Query(description="Judge the rule on this date")] = None,
    user_id: OptionalUserIdDep = None,
) -> ScreenerPageOut:
    if rule is not None and setup_version_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Send rule or setup_version_id, not both")
    rule_text = rule.strip() if rule and rule.strip() else None
    if setup_version_id is not None:
        try:
            version = setups.visible_version(session, setup_version_id, user_id)
        except setups.SetupNotFound as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Setup version {setup_version_id} not found"
            ) from exc
        rule_text = version.rule_text
    compiled = compile_or_422(rule_text) if rule_text else None
    if compiled is not None and compiled.user_scoped and user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "This rule reads your drawings (drawing() or avwap()); sign in to run it",
        )
    result = run_screen_full(
        session,
        ScreenQuery(
            markets=_csv(market),
            exchanges=_csv(exchange),
            currencies=_csv(currency),
            sector=sector,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            momentum_days=momentum_days,
            momentum_min=momentum_min,
            momentum_max=momentum_max,
            near_52w_high=near_52w_high,
            near_52w_low=near_52w_low,
            above_sma_50=above_sma_50,
            above_sma_200=above_sma_200,
            hv_min=hv_min,
            hv_max=hv_max,
            atr_pct_min=atr_pct_min,
            atr_pct_max=atr_pct_max,
            sentiment_min=sentiment_min,
            sentiment_max=sentiment_max,
            fundamentals={
                "pe": (pe_min, pe_max),
                "pb": (pb_min, pb_max),
                "ps": (ps_min, ps_max),
                "ev_ebitda": (ev_ebitda_min, ev_ebitda_max),
                "dividend_yield": (dividend_yield_min, dividend_yield_max),
                "market_cap_usd": (market_cap_usd_min, market_cap_usd_max),
                "net_margin": (net_margin_min, net_margin_max),
                "roe": (roe_min, roe_max),
                "debt_to_equity": (debt_to_equity_min, debt_to_equity_max),
                "revenue_growth": (revenue_growth_min, revenue_growth_max),
            },
            sort=sort,
            descending=dir == "desc",
            offset=offset,
            limit=limit,
            rule=compiled,
            rule_user_id=user_id if compiled is not None and compiled.user_scoped else None,
            rule_mode=rule_mode,
            as_of=as_of,
        ),
    )
    rule_out = None
    if compiled is not None and result.rule_run is not None:
        rule_out = ScreenerRuleOut(
            text=compiled.text,
            canonical=compiled.canonical_text,
            hash=compiled.hash,
            setup_version_id=setup_version_id,
            mode=rule_mode,
            as_of=as_of,
            sessions=result.rule_run.sessions,
            counts=ScreenerRuleCountsOut(**result.counts),
            evaluated=sum(result.counts.values()),
            cached=result.rule_run.cached,
            user_scoped=compiled.user_scoped,
        )
    return ScreenerPageOut(
        rows=[ScreenerRowOut.model_validate(r, from_attributes=True) for r in result.rows],
        total=result.total,
        offset=offset,
        limit=limit,
        universe=screen_universe(),
        rule=rule_out,
    )


@router.get("/screen", response_model=list[ScreenerResultOut])
@limiter.limit("30/minute")
def screen_symbols(
    request: Request,
    session: SessionDep,
    sector: Annotated[str | None, Query()] = None,
    rsi_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    rsi_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    momentum_days: Annotated[int | None, Query(ge=1, le=MAX_MOMENTUM_DAYS)] = None,
    momentum_min: Annotated[float | None, Query()] = None,
    momentum_max: Annotated[float | None, Query()] = None,
    near_52w_high: Annotated[bool, Query()] = False,
    near_52w_low: Annotated[bool, Query()] = False,
    sentiment_min: Annotated[float | None, Query(ge=-1, le=1)] = None,
    sentiment_max: Annotated[float | None, Query(ge=-1, le=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_RESULTS)] = MAX_RESULTS,
) -> list[ScreenerResultOut]:
    """The original list screen, on the unified query path (RS-5 fixed)."""
    rows, _total = run_screen(
        session,
        ScreenQuery(
            sector=sector,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            momentum_days=momentum_days,
            momentum_min=momentum_min,
            momentum_max=momentum_max,
            near_52w_high=near_52w_high,
            near_52w_low=near_52w_low,
            sentiment_min=sentiment_min,
            sentiment_max=sentiment_max,
            limit=limit,
        ),
    )
    return [
        ScreenerResultOut(
            ticker=r.ticker,
            name=r.name,
            sector=r.sector,
            exchange=r.exchange,
            currency=r.currency,
            last_close=r.last_close,
            as_of=r.as_of,
            rsi_14=r.rsi_14,
            momentum_pct=r.momentum_pct,
            momentum_days=r.momentum_days,
            high_52w=r.high_52w,
            low_52w=r.low_52w,
            sentiment_7d=r.sentiment_7d,
        )
        for r in rows
        # A metrics row always has these (it is written from at least one
        # bar); a row without them is skipped, never shown as 0 (RS-4).
        if r.last_close is not None and r.high_52w is not None and r.low_52w is not None
    ]
