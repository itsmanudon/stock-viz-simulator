"""``stockviz.cli news`` — the manual twin of the news-ingest worker.

The point of these tests is that the CLI is not a second implementation: it
must reach the same handler the Kafka consumer reaches, so de-duplication, the
inbox receipt and the ``news.article.ingested`` fan-out all come along for free.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from stockviz import cli
from stockviz.events.contracts import (
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    NEWS_TOPIC,
)
from stockviz.events.outbox import (
    build_news_refresh_requested,
    parse_news_refresh_requested,
)
from stockviz.models import ConsumerInbox, NewsArticle, OutboxEvent, Symbol
from stockviz.services.ingest.news import ArticleRecord

PUBLISHED = datetime(2026, 8, 28, 12, 0, 0)


@pytest.fixture
def wired(engine, monkeypatch):
    """Point the CLI, the worker and the scheduler helpers at the test engine."""
    monkeypatch.setattr("stockviz.cli.engine", engine)
    monkeypatch.setattr("stockviz.scheduler.engine", engine)
    monkeypatch.setattr("stockviz.workers.news_ingest_consumer.engine", engine)
    monkeypatch.setattr(
        "stockviz.cli.get_settings", lambda: SimpleNamespace(newsdata_key="test-key")
    )
    return engine


def article(url: str, ticker: str = "AAPL", title: str = "Headline") -> ArticleRecord:
    return ArticleRecord(
        ticker=ticker,
        title=title,
        url=url,
        source="example",
        published_at=PUBLISHED,
        summary="A lede.",
        image_url=None,
    )


def stub_fetch(monkeypatch, articles: list[ArticleRecord], calls: list | None = None):
    """Replace only the worker's provider I/O — the persistence path stays real."""

    def _fetch(event):
        if calls is not None:
            calls.append(event.payload.company_name)
        return list(articles)

    monkeypatch.setattr("stockviz.workers.news_ingest_consumer.fetch_articles_for_event", _fetch)


def symbol(session: Session, ticker: str, name: str) -> None:
    session.add(Symbol(ticker=ticker, name=name, is_active=True))
    session.commit()


def run(*tickers: str) -> int:
    return cli.main(["news", *tickers])


# --- guard rails -------------------------------------------------------------


def test_news_refuses_to_run_without_a_newsdata_key(wired, monkeypatch, capsys):
    monkeypatch.setattr("stockviz.cli.get_settings", lambda: SimpleNamespace(newsdata_key=""))

    def _boom(*_a, **_k):
        raise AssertionError("must not call the provider without a key")

    monkeypatch.setattr("stockviz.workers.news_ingest_consumer.fetch_articles_for_event", _boom)
    assert run("AAPL") == 2
    assert "NEWSDATA_KEY" in capsys.readouterr().err


# --- the ingest path ---------------------------------------------------------


def test_news_persists_articles_and_emits_ingested_events(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    stub_fetch(monkeypatch, [article("https://example.com/a"), article("https://example.com/b")])

    assert run("AAPL") == 0

    rows = session.exec(select(NewsArticle)).all()
    assert {r.url for r in rows} == {"https://example.com/a", "https://example.com/b"}
    assert all(r.ticker == "AAPL" and r.published_at == PUBLISHED for r in rows)

    emitted = session.exec(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE_NEWS_ARTICLE_INGESTED)
    ).all()
    assert len(emitted) == 2
    assert {e.topic for e in emitted} == {NEWS_TOPIC}
    assert {e.partition_key for e in emitted} == {"AAPL"}


def test_news_uses_the_company_name_as_the_query(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    calls: list[str] = []
    stub_fetch(monkeypatch, [article("https://example.com/a")], calls)

    run("AAPL")

    assert calls == ["Apple Inc."]


def test_news_falls_back_to_the_ticker_when_no_name_is_known(wired, session, monkeypatch):
    calls: list[str] = []
    stub_fetch(monkeypatch, [article("https://example.com/a", ticker="ZZZZ")], calls)

    run("ZZZZ")

    assert calls == ["ZZZZ"]


def test_news_lowercase_ticker_is_normalised(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    calls: list[str] = []
    stub_fetch(monkeypatch, [article("https://example.com/a")], calls)

    run("aapl")

    assert calls == ["Apple Inc."]


def test_news_defaults_to_every_active_symbol(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    symbol(session, "MSFT", "Microsoft Corporation")
    session.add(Symbol(ticker="DEAD", name="Delisted Co", is_active=False))
    session.commit()
    calls: list[str] = []
    stub_fetch(monkeypatch, [], calls)

    assert run() == 0

    assert sorted(calls) == ["Apple Inc.", "Microsoft Corporation"]


# --- de-duplication ----------------------------------------------------------


def test_news_rerun_inserts_nothing_for_the_same_urls(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    stub_fetch(monkeypatch, [article("https://example.com/a"), article("https://example.com/b")])

    run("AAPL")
    run("AAPL")

    assert len(session.exec(select(NewsArticle)).all()) == 2
    emitted = session.exec(
        select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE_NEWS_ARTICLE_INGESTED)
    ).all()
    assert len(emitted) == 2, "a duplicate article must not re-emit an ingested event"


def test_news_only_new_urls_are_inserted_on_a_second_run(wired, session, monkeypatch):
    symbol(session, "AAPL", "Apple Inc.")
    stub_fetch(monkeypatch, [article("https://example.com/a")])
    run("AAPL")

    stub_fetch(monkeypatch, [article("https://example.com/a"), article("https://example.com/c")])
    run("AAPL")

    urls = {r.url for r in session.exec(select(NewsArticle)).all()}
    assert urls == {"https://example.com/a", "https://example.com/c"}


def test_news_writes_an_inbox_receipt_so_the_worker_would_skip_a_replay(
    wired, session, monkeypatch
):
    symbol(session, "AAPL", "Apple Inc.")
    stub_fetch(monkeypatch, [article("https://example.com/a")])

    run("AAPL")

    receipts = session.exec(select(ConsumerInbox)).all()
    assert len(receipts) == 1
    assert receipts[0].consumer_name == "stockviz.news-ingestion.v1"


# --- the envelope the CLI and the scheduler share ----------------------------


def test_build_news_refresh_requested_matches_the_scheduled_contract():
    envelope = build_news_refresh_requested(
        ticker="aapl", company_name="Apple Inc.", reason="manual"
    )
    payload = envelope.model_dump(mode="json")

    assert payload["event_type"] == EVENT_TYPE_NEWS_REFRESH_REQUESTED
    # Round-trips through the same parser the Kafka consumer uses.
    parsed = parse_news_refresh_requested(payload)
    assert parsed.payload.ticker == "AAPL"
    assert parsed.aggregate_id == "AAPL"
    assert parsed.payload.company_name == "Apple Inc."
    assert parsed.payload.reason == "manual"
