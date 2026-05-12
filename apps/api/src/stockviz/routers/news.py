"""`/v1/symbols/{ticker}/news` and `/v1/news`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import NewsArticle, Symbol
from stockviz.schemas import NewsArticleOut

router = APIRouter(prefix="/v1", tags=["news"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/symbols/{ticker}/news", response_model=list[NewsArticleOut])
@limiter.limit("60/minute")
def news_for_ticker(
    request: Request,
    ticker: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[NewsArticle]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    stmt = (
        select(NewsArticle)
        .where(NewsArticle.ticker == ticker)
        .order_by(NewsArticle.published_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(stmt).all())


@router.get("/news", response_model=list[NewsArticleOut])
@limiter.limit("60/minute")
def latest_news(
    request: Request,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NewsArticle]:
    stmt = (
        select(NewsArticle)
        .order_by(NewsArticle.published_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(stmt).all())
