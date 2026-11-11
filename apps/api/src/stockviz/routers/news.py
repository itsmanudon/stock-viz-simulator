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

MAX_TICKERS = 100
"""More symbols than any watchlist or portfolio holds; bounds the IN list."""


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
    tickers: Annotated[
        str | None,
        Query(
            max_length=1000,
            description="Comma-separated symbols, e.g. a watchlist or a portfolio's holdings",
        ),
    ] = None,
) -> list[NewsArticleOut]:
    wanted: list[str] | None = None
    if tickers is not None:
        wanted = sorted({t.strip().upper() for t in tickers.split(",") if t.strip()})[:MAX_TICKERS]
        if not wanted:
            return []
    return [_out(item) for item in news_items(session, tickers=wanted, limit=limit)]
