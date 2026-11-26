"""`/v1/symbols/{ticker}/news` and `/v1/news`, read from the Aegis copies.

Since Phase 2 news comes from Aegis News through the nightly
``stockviz.cli aegis-sync``. These routes read the copied tables and never
call Aegis. Newest first by ``available_at``, never ``published_at``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import (
    NewsArticleOut,
    NewsDayOut,
    NewsFacetOut,
    NewsFeedItemOut,
    NewsFeedOut,
    NewsHeatCellOut,
    NewsHeatRowOut,
    NewsOverviewOut,
    NewsReactionOut,
)
from stockviz.services.aegis import feed as news_feed
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
    scope: Annotated[
        Literal["symbols", "market"],
        Query(
            description=(
                "symbols: documents linked to a StockViz symbol (default). "
                "market: general headlines linked to none; cannot be combined with tickers"
            ),
        ),
    ] = "symbols",
) -> list[NewsArticleOut]:
    if scope == "market":
        if tickers is not None:
            raise HTTPException(status_code=400, detail="scope=market takes no tickers")
        return [_out(item) for item in news_items(session, limit=limit, market=True)]
    wanted: list[str] | None = None
    if tickers is not None:
        wanted = sorted({t.strip().upper() for t in tickers.split(",") if t.strip()})[:MAX_TICKERS]
        if not wanted:
            return []
    return [_out(item) for item in news_items(session, tickers=wanted, limit=limit)]


# ---------------------------------------------------------------------------
# The news page's archive (news redesign, 26 Nov 2026): every filter, keyset
# paging through the whole archive, price reactions, timeline and heatmap.
# ---------------------------------------------------------------------------


def _csv(raw: str | None, *, upper: bool = False, limit: int = MAX_TICKERS) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = [v.strip() for v in raw.split(",") if v.strip()]
    values = [v.upper() for v in values] if upper else values
    return tuple(dict.fromkeys(values))[:limit]


def _filters(
    q: str | None,
    tickers: str | None,
    sentiment: str | None,
    topic: str | None,
    source: str | None,
    scope: Literal["symbols", "market", "all"],
    since: date | None,
    until: date | None,
) -> news_feed.FeedFilters:
    wanted = _csv(tickers, upper=True)
    if scope == "market" and wanted:
        raise HTTPException(status_code=400, detail="scope=market takes no tickers")
    sentiments = _csv(sentiment)
    unknown = [s for s in sentiments if s not in (*news_feed.SENTIMENTS, news_feed.UNSCORED)]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sentiment {unknown[0]!r}: positive, neutral, negative, mixed or unscored",
        )
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="from is after to")
    return news_feed.FeedFilters(
        q=(q or "").strip() or None,
        tickers=wanted,
        sentiments=sentiments,
        topics=_csv(topic, limit=20),
        sources=_csv(source, limit=20),
        scope=scope,
        since=since,
        until=until,
    )


QText = Annotated[str | None, Query(max_length=200, description="Words the headline must contain")]
QTickers = Annotated[str | None, Query(max_length=1000, description="Comma-separated symbols")]
QSentiment = Annotated[
    str | None,
    Query(
        max_length=200, description="Comma-separated: positive, neutral, negative, mixed, unscored"
    ),
]
QTopic = Annotated[str | None, Query(max_length=1000, description="Comma-separated Aegis topics")]
QSource = Annotated[str | None, Query(max_length=2000, description="Comma-separated source names")]
QScope = Annotated[
    Literal["symbols", "market", "all"],
    Query(
        description="symbols (default): linked to a StockViz symbol; market: linked to none; all"
    ),
]
QFrom = Annotated[
    date | None, Query(alias="from", description="UTC date of available_at, inclusive")
]
QTo = Annotated[date | None, Query(alias="to", description="UTC date of available_at, inclusive")]


@router.get("/news/feed", response_model=NewsFeedOut)
@limiter.limit("60/minute")
def news_feed_page(
    request: Request,
    session: SessionDep,
    q: QText = None,
    tickers: QTickers = None,
    sentiment: QSentiment = None,
    topic: QTopic = None,
    source: QSource = None,
    scope: QScope = "symbols",
    since: QFrom = None,
    until: QTo = None,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> NewsFeedOut:
    filters = _filters(q, tickers, sentiment, topic, source, scope, since, until)
    try:
        page = news_feed.feed(session, filters, cursor=cursor, limit=limit)
    except news_feed.CursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = []
    for item in page.items:
        base = _out(item)
        items.append(
            NewsFeedItemOut(
                **base.model_dump(),
                reactions=[
                    NewsReactionOut(
                        ticker=r.ticker,
                        session_date=r.session_date,
                        change_pct=r.change_pct,
                        closes=r.closes,
                        reaction_index=r.reaction_index,
                    )
                    for r in page.reactions.get(item.document.document_id, [])
                ],
            )
        )
    return NewsFeedOut(items=items, next_cursor=page.next_cursor, total=page.total)


@router.get("/news/overview", response_model=NewsOverviewOut)
@limiter.limit("60/minute")
def news_overview(
    request: Request,
    session: SessionDep,
    q: QText = None,
    tickers: QTickers = None,
    sentiment: QSentiment = None,
    topic: QTopic = None,
    source: QSource = None,
    scope: QScope = "symbols",
    since: QFrom = None,
    until: QTo = None,
) -> NewsOverviewOut:
    filters = _filters(q, tickers, sentiment, topic, source, scope, since, until)
    data = news_feed.overview(session, filters)
    return NewsOverviewOut(
        total=data.total,
        first_date=data.first_date,
        last_date=data.last_date,
        days=[NewsDayOut.model_validate(d) for d in data.days],
        sentiments=data.sentiments,
        topics=[NewsFacetOut(value=v, count=c) for v, c in data.topics],
        sources=[NewsFacetOut(value=v, count=c) for v, c in data.sources],
        heatmap_days=data.heatmap_days,
        heatmap=[
            NewsHeatRowOut(
                ticker=str(row["ticker"]),
                total=int(row["total"]),  # type: ignore[arg-type]
                cells=[NewsHeatCellOut.model_validate(c) for c in row["cells"]],  # type: ignore[union-attr]
            )
            for row in data.heatmap_rows
        ],
    )
