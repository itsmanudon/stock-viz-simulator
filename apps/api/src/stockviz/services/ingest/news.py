"""News ingest (newsdata.io).

The free tier returns the 10 latest articles per query. We query per ticker by
company name and dedupe on ``url`` via the unique constraint.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from stockviz.models import NewsArticle
from stockviz.services.sentiment import score_headlines

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArticleRecord:
    ticker: str | None
    title: str
    url: str
    source: str | None
    published_at: datetime
    summary: str | None
    image_url: str | None
    sentiment: str | None = None


NewsdataFetchFn = Callable[[str, str], dict[str, Any]]
"""(api_key, query) -> raw JSON dict."""


def _default_newsdata_fetch(api_key: str, query: str) -> dict[str, Any]:
    response = httpx.get(
        "https://newsdata.io/api/1/latest",
        params={"apikey": api_key, "qInTitle": query, "language": "en"},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    # newsdata.io: "2025-04-13 07:17:01"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    logger.warning("news: unrecognized pubDate format: %r", value)
    return None


def fetch_newsdata(
    *,
    api_key: str,
    query: str,
    ticker: str | None = None,
    fetch_fn: NewsdataFetchFn = _default_newsdata_fetch,
) -> list[ArticleRecord]:
    """Return parsed articles for a single newsdata.io query.

    ``ticker`` is informational — it gets stamped onto each article so the
    write side knows which symbol the query was for.
    """

    if not api_key:
        return []

    payload = fetch_fn(api_key, query)
    results = payload.get("results") or []

    articles: list[ArticleRecord] = []
    for item in results:
        url = item.get("link") or item.get("url")
        title = item.get("title")
        published = _parse_published_at(item.get("pubDate"))
        if not url or not title or published is None:
            continue
        articles.append(
            ArticleRecord(
                ticker=ticker,
                title=title,
                url=url,
                source=item.get("source_id") or item.get("source_name"),
                published_at=published,
                summary=item.get("description"),
                image_url=item.get("image_url") or None,
            )
        )
    return articles


def upsert_articles(session: Session, articles: list[ArticleRecord]) -> int:
    """Insert articles, skipping any whose URL is already in the table."""

    if not articles:
        return 0

    rows = [
        {
            "ticker": a.ticker,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "summary": a.summary,
            "image_url": a.image_url,
            "sentiment": a.sentiment,
        }
        for a in articles
    ]
    stmt = pg_insert(NewsArticle).values(rows).on_conflict_do_nothing(index_elements=["url"])
    session.exec(stmt)  # type: ignore[arg-type]
    session.commit()
    return len(rows)


def ingest_news_for_ticker(
    session: Session,
    *,
    ticker: str,
    company_name: str,
    newsdata_key: str,
    anthropic_api_key: str = "",
) -> int:
    articles = fetch_newsdata(api_key=newsdata_key, query=company_name, ticker=ticker)
    if articles and anthropic_api_key:
        sentiments = score_headlines([a.title for a in articles], api_key=anthropic_api_key)
        articles = [
            ArticleRecord(
                ticker=a.ticker,
                title=a.title,
                url=a.url,
                source=a.source,
                published_at=a.published_at,
                summary=a.summary,
                image_url=a.image_url,
                sentiment=s,
            )
            for a, s in zip(articles, sentiments, strict=True)
        ]
    return upsert_articles(session, articles)
