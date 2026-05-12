"""`/v1/recommendations` — latest recommendation per ticker.

Reads pre-computed rows from the ``recommendations`` table (the scheduler
recomputes daily; the CLI can force a recompute). Joins with ``symbols``
so the response includes the company name + sector without a second
round-trip.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Recommendation, Symbol
from stockviz.schemas import RecommendationOut

router = APIRouter(prefix="/v1", tags=["recommendations"])

SessionDep = Annotated[Session, Depends(get_session)]


def _parse_rationale(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [chunk.strip() for chunk in raw.split(";") if chunk.strip()]


@router.get("/recommendations", response_model=list[RecommendationOut])
@limiter.limit("60/minute")
def list_recommendations(
    request: Request,
    session: SessionDep,
    min_score: Annotated[int, Query(ge=0, le=6)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RecommendationOut]:
    # Per-ticker latest computed_at, joined back so we get the score + rationale
    # for that exact row.
    latest = (
        select(Recommendation.ticker, func.max(Recommendation.computed_at).label("computed_at"))
        .group_by(Recommendation.ticker)
        .subquery()
    )
    stmt = (
        select(Recommendation, Symbol)
        .join(
            latest,
            (Recommendation.ticker == latest.c.ticker)  # type: ignore[arg-type]
            & (Recommendation.computed_at == latest.c.computed_at),  # type: ignore[arg-type]
        )
        .join(Symbol, Symbol.ticker == Recommendation.ticker)  # type: ignore[arg-type]
        .where(Recommendation.score >= min_score)
        .order_by(Recommendation.score.desc(), Recommendation.ticker)  # type: ignore[attr-defined]
        .limit(limit)
    )

    out: list[RecommendationOut] = []
    for rec, symbol in session.exec(stmt).all():
        out.append(
            RecommendationOut(
                ticker=rec.ticker,
                name=symbol.name,
                sector=symbol.sector,
                score=int(rec.score),
                rationale=_parse_rationale(rec.rationale),
                computed_at=rec.computed_at,
            )
        )
    return out
