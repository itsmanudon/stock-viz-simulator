"""`/v1/symbols/{ticker}/news` and `/v1/news`, read from the Aegis copies.

Since Phase 2 news comes from Aegis News through the nightly
``stockviz.cli aegis-sync``. These routes read the copied tables and never
call Aegis. Newest first by ``available_at``, never ``published_at``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import NewsArticleOut
from stockviz.services.aegis.read import NewsItem, news_items

router = APIRouter(prefix="/v1", tags=["news"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(item: NewsItem) -> NewsArticleOut:
    doc = item.document
    return NewsArticleOut(
        id=doc.document_id,
        tickers=list(item.tickers),
        title=doc.title,
        url=doc.url,
        source=doc.source_name,
        published_at=doc.published_at,
        available_at=doc.available_at,
        sentiment=item.sentiment
        if item.sentiment in ("positive", "neutral", "negative", "mixed")
        else None,
        sentiment_model=item.sentiment_model,
        topic=item.topic,
    )


@router.get("/symbols/{ticker}/news", response_model=list[NewsArticleOut])
@limiter.limit("60/minute")
def news_for_ticker(
    request: Request,
    ticker: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[NewsArticleOut]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    return [_out(item) for item in news_items(session, ticker=ticker, limit=limit)]


@router.get("/news", response_model=list[NewsArticleOut])
@limiter.limit("60/minute")
def latest_news(
    request: Request,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NewsArticleOut]:
    return [_out(item) for item in news_items(session, limit=limit)]
