"""Parser tests for the news ingest layer."""

from __future__ import annotations

from datetime import datetime

from stockviz.services.ingest.news import fetch_newsdata

NEWSDATA_OK = {
    "status": "success",
    "totalResults": 2,
    "results": [
        {
            "article_id": "abc123",
            "title": "Apple beats earnings",
            "link": "https://example.com/apple-earnings",
            "description": "Apple reported strong Q2 results.",
            "pubDate": "2025-04-13 07:17:01",
            "image_url": "https://example.com/img.jpg",
            "source_id": "example",
            "source_name": "Example News",
        },
        {
            "article_id": "def456",
            "title": "Apple announces new iPhone",
            "link": "https://example.com/new-iphone",
            "description": None,
            "pubDate": "2025-04-12 10:00:00",
            "image_url": None,
            "source_id": "techcrunch",
        },
    ],
}

NEWSDATA_MALFORMED = {
    "status": "success",
    "results": [
        {"title": "missing link"},  # dropped
        {"link": "https://x.com/y", "title": "missing date"},  # dropped
        {
            "link": "https://x.com/ok",
            "title": "valid",
            "pubDate": "2025-04-12 10:00:00",
        },  # kept
    ],
}


def test_fetch_newsdata_parses_articles():
    articles = fetch_newsdata(
        api_key="k", query="Apple", ticker="AAPL", fetch_fn=lambda k, q: NEWSDATA_OK
    )
    assert len(articles) == 2
    first = articles[0]
    assert first.ticker == "AAPL"
    assert first.title == "Apple beats earnings"
    assert first.url == "https://example.com/apple-earnings"
    assert first.source == "example"
    assert first.published_at == datetime(2025, 4, 13, 7, 17, 1)
    assert first.image_url == "https://example.com/img.jpg"


def test_fetch_newsdata_skips_articles_missing_required_fields():
    articles = fetch_newsdata(api_key="k", query="X", fetch_fn=lambda k, q: NEWSDATA_MALFORMED)
    assert len(articles) == 1
    assert articles[0].title == "valid"


def test_fetch_newsdata_returns_empty_without_key():
    called = []

    def fake(*args):
        called.append(args)
        return NEWSDATA_OK

    assert fetch_newsdata(api_key="", query="X", fetch_fn=fake) == []
    assert called == []
