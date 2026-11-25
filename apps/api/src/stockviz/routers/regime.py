"""`GET /v1/regime`: the rule-based market regime per market (A3.5, M3.1).

Public, 60/min, cached in process for ten minutes (the inputs move once a
night) and sent with ``Cache-Control: public, max-age=600``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import MarketRegimeOut, RegimeInputOut, RegimeOut, RegimeRuleOut
from stockviz.services import regime as regime_service

router = APIRouter(prefix="/v1", tags=["regime"])

SessionDep = Annotated[Session, Depends(get_session)]

METHOD = (
    "Rules over four inputs, read in order: the first rule met names the state; an unknown "
    "input before that leaves the state unknown. Breadth counts the market's current symbol "
    "list (survivorship-biased). Volatility is realised, not implied (no VIX)."
)


@router.get("/regime", response_model=RegimeOut)
@limiter.limit("60/minute")
def get_regime(request: Request, response: Response, session: SessionDep) -> RegimeOut:
    response.headers["Cache-Control"] = f"public, max-age={regime_service.CACHE_SECONDS}"
    markets = []
    for m in regime_service.regimes(session):
        markets.append(
            MarketRegimeOut(
                market=m.market,  # pyright: ignore[reportArgumentType]
                name=m.name,
                index=m.index,
                index_name=m.index_name,
                as_of=m.as_of,
                state=m.state,  # pyright: ignore[reportArgumentType]
                reason=m.reason,
                inputs=[
                    RegimeInputOut(name=name, value=m.values.get(name), description=text)
                    for name, text in regime_service.INPUTS.items()
                ],
                rules=[
                    RegimeRuleOut(
                        state=rule.state,  # pyright: ignore[reportArgumentType]
                        rule=rule.text(),
                        description=rule.description,
                        met=met,
                    )
                    for rule, met in m.rules
                ],
                breadth_count=m.breadth_count,
                breadth_universe=m.breadth_universe,
                breadth_as_of=m.breadth_as_of,
                vol_window_sessions=m.vol_window_sessions,
                hv_20=m.hv_20,
            )
        )
    return RegimeOut(markets=markets, method=METHOD, disclaimer=regime_service.DISCLAIMER)
