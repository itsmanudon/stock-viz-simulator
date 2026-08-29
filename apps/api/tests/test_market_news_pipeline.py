"""Scheduler enqueue + handler atomicity for market/news/sentiment (SQLite)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlmodel import Session, select

from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    MARKET_TOPIC,
    NEWS_TOPIC,
)
from stockviz.events.handlers import (
    apply_market_bars_refreshed,
    apply_news_sentiment_scored,
    persist_article_sentiment,
    persist_market_refresh,
    persist_news_refresh,
    score_one_article,
)
from stockviz.events.outbox import (
    enqueue_market_refresh_requested,
    enqueue_news_refresh_requested,
    parse_market_bars_refreshed,
    parse_market_refresh_requested,
    parse_news_article_ingested,
    parse_news_refresh_requested,
    parse_news_sentiment_scored,
)
from stockviz.models import (
    Alert,
    AlertDirection,
    NewsArticle,
    NewsSentiment,
    OutboxEvent,
    PriceBar,
    Symbol,
    SymbolMetrics,
    User,
)
from stockviz.scheduler import (
    TOP_TICKERS_HOURLY,
    daily_price_refresh,
    hourly_top_movers,
    news_refresh,
)
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.news import ArticleRecord, ingest_news_for_ticker
from stockviz.services.ingest.prices import DAILY_INTERVAL, SOURCE_YFINANCE, BarRecord
from stockviz.services.sentiment.base import SentimentScore
from stockviz.services.sentiment.null_provider import NullProvider
from stockviz.workers.market_ingest_consumer import process_payload as market_ingest_process

BAR_START = datetime(2024, 1, 2)


def _symbol(session: Session, ticker: str, *, name: str | None = None) -> None:
    session.add(Symbol(ticker=ticker, name=name or ticker, currency="USD", is_active=True))
    session.commit()


def _bars(ticker: str, *, n: int = 20, close: Decimal = Decimal("100")) -> list[BarRecord]:
    out: list[BarRecord] = []
    for i in range(n):
        c = close + Decimal(i)
        out.append(
            BarRecord(
                ticker=ticker,
                ts=BAR_START + timedelta(days=i),
                interval=DAILY_INTERVAL,
                open=c,
                high=c,
                low=c,
                close=c,
                volume=Decimal("1000"),
                source=SOURCE_YFINANCE,
                adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
                session_scope=SessionScope.REGULAR,
            )
        )
    return out


def _outbox(session: Session, event_type: str) -> list[OutboxEvent]:
    return [row for row in session.exec(select(OutboxEvent)).all() if row.event_type == event_type]


def test_daily_price_refresh_enqueues_without_provider_io(
    session: Session, engine, monkeypatch
) -> None:
    monkeypatch.setattr("stockviz.scheduler.engine", engine)

    def _boom(*_a, **_k):
        raise AssertionError("provider I/O must not run in the scheduler")

    monkeypatch.setattr("stockviz.services.ingest.prices.ingest_ticker", _boom)
    monkeypatch.setattr("stockviz.services.ingest.prices.fetch_daily_bars", _boom)
    _symbol(session, "AAPL")
    daily_price_refresh()
    rows = _outbox(session, EVENT_TYPE_MARKET_REFRESH_REQUESTED)
    assert len(rows) == 1
    assert rows[0].topic == MARKET_TOPIC
    assert rows[0].partition_key == "AAPL"
    event = parse_market_refresh_requested(rows[0].payload)
    assert event.payload.reason == "daily"
    assert session.exec(select(PriceBar)).all() == []


def test_hourly_top_movers_enqueues_and_skips_alerts(session: Session, engine, monkeypatch) -> None:
    monkeypatch.setattr("stockviz.scheduler.engine", engine)
    called = []
    monkeypatch.setattr(
        "stockviz.services.alerts.evaluate_pending_alerts",
        lambda *a, **k: called.append(1) or 0,
    )
    hourly_top_movers()
    rows = _outbox(session, EVENT_TYPE_MARKET_REFRESH_REQUESTED)
    assert len(rows) == len(TOP_TICKERS_HOURLY)
    assert {row.partition_key for row in rows} == set(TOP_TICKERS_HOURLY)
    assert all(parse_market_refresh_requested(r.payload).payload.reason == "hourly" for r in rows)
    assert called == []


def test_news_refresh_enqueues_without_provider_io(session: Session, engine, monkeypatch) -> None:
    monkeypatch.setattr("stockviz.scheduler.engine", engine)
    monkeypatch.setattr(
        "stockviz.scheduler.get_settings",
        lambda: SimpleNamespace(newsdata_key="test-key"),
    )

    def _boom(*_a, **_k):
        raise AssertionError("news provider I/O must not run in the scheduler")

    monkeypatch.setattr("stockviz.services.ingest.news.ingest_news_for_ticker", _boom)
    monkeypatch.setattr("stockviz.services.ingest.news.fetch_newsdata", _boom)
    _symbol(session, "AAPL", name="Apple Inc.")
    news_refresh()
    rows = _outbox(session, EVENT_TYPE_NEWS_REFRESH_REQUESTED)
    assert len(rows) == 1
    assert rows[0].topic == NEWS_TOPIC
    event = parse_news_refresh_requested(rows[0].payload)
    assert event.payload.reason == "scheduled"


def test_market_ingest_persists_bars_and_outbox_atomically(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_market_refresh_requested(session, ticker="AAPL", reason="manual")
    session.commit()
    event = parse_market_refresh_requested(req.payload)
    bars = _bars("AAPL", close=Decimal("150"))
    result = persist_market_refresh(session, event, bars)
    session.commit()
    assert result == "applied"
    stored = session.exec(select(PriceBar).where(PriceBar.ticker == "AAPL")).all()
    assert len(stored) == 20
    refreshed = _outbox(session, EVENT_TYPE_MARKET_BARS_REFRESHED)
    assert len(refreshed) == 1
    payload = parse_market_bars_refreshed(refreshed[0].payload).payload
    assert payload.ticker == "AAPL"
    assert payload.bar_count == 20
    assert payload.request_event_id == str(event.event_id)


def test_duplicate_market_refresh_is_db_safe(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_market_refresh_requested(session, ticker="AAPL", reason="daily")
    session.commit()
    event = parse_market_refresh_requested(req.payload)
    persist_market_refresh(session, event, _bars("AAPL"))
    session.commit()
    again = persist_market_refresh(session, event, _bars("AAPL", close=Decimal("999")))
    session.commit()
    assert again == "duplicate"
    assert len(_outbox(session, EVENT_TYPE_MARKET_BARS_REFRESHED)) == 1
    latest = max(
        session.exec(select(PriceBar).where(PriceBar.ticker == "AAPL")).all(),
        key=lambda b: b.ts,
    )
    assert latest.close != Decimal("999") + Decimal(19)


def test_failed_market_transaction_writes_nothing(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_market_refresh_requested(session, ticker="AAPL", reason="daily")
    session.commit()
    event = parse_market_refresh_requested(req.payload)
    persist_market_refresh(session, event, _bars("AAPL"))
    session.flush()
    assert session.exec(select(PriceBar)).all()
    session.rollback()
    assert session.exec(select(PriceBar)).all() == []
    assert _outbox(session, EVENT_TYPE_MARKET_BARS_REFRESHED) == []


def test_empty_provider_result_marks_processed_without_refreshed_event(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_market_refresh_requested(session, ticker="AAPL", reason="daily")
    session.commit()
    event = parse_market_refresh_requested(req.payload)
    result = persist_market_refresh(session, event, [])
    session.commit()
    assert result == "applied"
    assert session.exec(select(PriceBar)).all() == []
    assert _outbox(session, EVENT_TYPE_MARKET_BARS_REFRESHED) == []
    assert persist_market_refresh(session, event, _bars("AAPL")) == "duplicate"


def test_market_analytics_is_ticker_scoped_and_evaluates_alerts(session: Session) -> None:
    _symbol(session, "AAPL")
    _symbol(session, "MSFT")
    user = User(email="alerts@stockviz.dev", name="A")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    session.add(
        Alert(
            user_id=user.id,
            ticker="AAPL",
            direction=AlertDirection.ABOVE,
            target_price=Decimal("155"),
        )
    )
    session.commit()
    req = enqueue_market_refresh_requested(session, ticker="AAPL", reason="hourly")
    session.commit()
    event = parse_market_refresh_requested(req.payload)
    persist_market_refresh(session, event, _bars("AAPL", close=Decimal("150")))
    session.commit()
    # Unrelated ticker has bars but must not get metrics from AAPL's event.
    for bar in _bars("MSFT", close=Decimal("10")):
        session.add(
            PriceBar(
                ticker=bar.ticker,
                ts=bar.ts,
                interval=bar.interval,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=int(bar.volume),
                source=bar.source,
            )
        )
    session.commit()
    refreshed = parse_market_bars_refreshed(
        _outbox(session, EVENT_TYPE_MARKET_BARS_REFRESHED)[0].payload
    )
    apply_market_bars_refreshed(session, refreshed)
    session.commit()
    aapl = session.get(SymbolMetrics, "AAPL")
    msft = session.get(SymbolMetrics, "MSFT")
    assert aapl is not None
    assert aapl.last_close == Decimal("169")
    assert msft is None
    alert = session.exec(select(Alert)).one()
    assert alert.triggered_at is not None
    dup = apply_market_bars_refreshed(session, refreshed)
    session.commit()
    assert dup == "duplicate"


def test_market_ingest_process_ignores_other_types() -> None:
    assert market_ingest_process({"event_type": EVENT_TYPE_MARKET_BARS_REFRESHED}) == "ignored"


def test_news_ingest_emits_one_event_per_new_url(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple Inc.", reason="manual"
    )
    session.commit()
    event = parse_news_refresh_requested(req.payload)
    articles = [
        ArticleRecord(
            ticker="AAPL",
            title="One",
            url="https://example.test/aapl-1",
            source="reuters",
            published_at=BAR_START,
            summary="hello",
            image_url=None,
        ),
        ArticleRecord(
            ticker="AAPL",
            title="Two",
            url="https://example.test/aapl-2",
            source="reuters",
            published_at=BAR_START,
            summary="hello",
            image_url=None,
        ),
    ]
    persist_news_refresh(session, event, articles)
    session.commit()
    ingested = _outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)
    assert len(ingested) == 2
    assert {parse_news_article_ingested(r.payload).payload.url for r in ingested} == {
        "https://example.test/aapl-1",
        "https://example.test/aapl-2",
    }
    persist_news_refresh(session, event, articles)
    session.commit()
    assert len(_outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)) == 2


def test_duplicate_url_does_not_emit_second_article_event(session: Session) -> None:
    _symbol(session, "AAPL")
    first = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="scheduled"
    )
    session.commit()
    article = ArticleRecord(
        ticker="AAPL",
        title="One",
        url="https://example.test/same",
        source="x",
        published_at=BAR_START,
        summary=None,
        image_url=None,
    )
    persist_news_refresh(session, parse_news_refresh_requested(first.payload), [article])
    session.commit()
    second = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="scheduled"
    )
    session.commit()
    persist_news_refresh(session, parse_news_refresh_requested(second.payload), [article])
    session.commit()
    assert session.exec(select(NewsArticle)).all().__len__() == 1
    assert len(_outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)) == 1


def test_news_ingest_does_not_score_sentiment(session: Session, monkeypatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(
        "stockviz.services.sentiment.store.score_articles",
        lambda *a, **k: called.append(1) or 0,
    )
    monkeypatch.setattr(
        "stockviz.services.ingest.news.fetch_newsdata",
        lambda **k: [
            ArticleRecord(
                ticker="AAPL",
                title="H",
                url="https://example.test/noscore",
                source="x",
                published_at=BAR_START,
                summary=None,
                image_url=None,
            )
        ],
    )
    _symbol(session, "AAPL")
    ingest_news_for_ticker(
        session,
        ticker="AAPL",
        company_name="Apple",
        newsdata_key="k",
        score_sentiment=True,
    )
    assert called == []
    assert session.exec(select(NewsSentiment)).all() == []
    assert session.exec(select(NewsArticle)).all()


def test_sentiment_consumer_persists_score_and_outbox_atomically(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="manual"
    )
    session.commit()
    persist_news_refresh(
        session,
        parse_news_refresh_requested(req.payload),
        [
            ArticleRecord(
                ticker="AAPL",
                title="Rally",
                url="https://example.test/rally",
                source="x",
                published_at=BAR_START,
                summary="up",
                image_url=None,
            )
        ],
    )
    session.commit()
    ingested = parse_news_article_ingested(
        _outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)[0].payload
    )
    score = SentimentScore(label="positive", score=0.7421, model="fake-v1", confidence=0.91)
    persist_article_sentiment(session, ingested, score)
    session.commit()
    row = session.exec(select(NewsSentiment)).one()
    assert row.model == "fake-v1"
    assert row.label == "positive"
    scored = _outbox(session, EVENT_TYPE_NEWS_SENTIMENT_SCORED)
    assert len(scored) == 1
    assert persist_article_sentiment(session, ingested, score) == "duplicate"
    session.commit()
    assert len(session.exec(select(NewsSentiment)).all()) == 1


def test_failed_sentiment_transaction_writes_nothing(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="manual"
    )
    session.commit()
    persist_news_refresh(
        session,
        parse_news_refresh_requested(req.payload),
        [
            ArticleRecord(
                ticker="AAPL",
                title="Rally",
                url="https://example.test/atomic",
                source="x",
                published_at=BAR_START,
                summary=None,
                image_url=None,
            )
        ],
    )
    session.commit()
    ingested = parse_news_article_ingested(
        _outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)[0].payload
    )
    persist_article_sentiment(
        session,
        ingested,
        SentimentScore(label="negative", score=-0.4, model="fake-v1", confidence=None),
    )
    session.flush()
    session.rollback()
    assert session.exec(select(NewsSentiment)).all() == []
    assert _outbox(session, EVENT_TYPE_NEWS_SENTIMENT_SCORED) == []


def test_null_provider_records_inbox_without_scored_event(session: Session) -> None:
    _symbol(session, "AAPL")
    req = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="manual"
    )
    session.commit()
    persist_news_refresh(
        session,
        parse_news_refresh_requested(req.payload),
        [
            ArticleRecord(
                ticker="AAPL",
                title="None",
                url="https://example.test/null",
                source="x",
                published_at=BAR_START,
                summary=None,
                image_url=None,
            )
        ],
    )
    session.commit()
    ingested = parse_news_article_ingested(
        _outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)[0].payload
    )
    article = session.exec(select(NewsArticle)).one()
    assert score_one_article(article, provider=NullProvider()) is None
    persist_article_sentiment(session, ingested, None)
    session.commit()
    assert session.exec(select(NewsSentiment)).all() == []
    assert _outbox(session, EVENT_TYPE_NEWS_SENTIMENT_SCORED) == []


def test_sentiment_aggregate_is_ticker_scoped(session: Session) -> None:
    _symbol(session, "AAPL")
    _symbol(session, "MSFT")
    req = enqueue_news_refresh_requested(
        session, ticker="AAPL", company_name="Apple", reason="manual"
    )
    session.commit()
    persist_news_refresh(
        session,
        parse_news_refresh_requested(req.payload),
        [
            ArticleRecord(
                ticker="AAPL",
                title="Good",
                url="https://example.test/good",
                source="x",
                published_at=datetime.now() - timedelta(hours=1),
                summary=None,
                image_url=None,
            )
        ],
    )
    session.commit()
    ingested = parse_news_article_ingested(
        _outbox(session, EVENT_TYPE_NEWS_ARTICLE_INGESTED)[0].payload
    )
    persist_article_sentiment(
        session,
        ingested,
        SentimentScore(label="positive", score=0.8, model="fake-v1", confidence=0.9),
    )
    session.commit()
    scored = parse_news_sentiment_scored(
        _outbox(session, EVENT_TYPE_NEWS_SENTIMENT_SCORED)[0].payload
    )
    apply_news_sentiment_scored(session, scored)
    session.commit()
    aapl = session.get(SymbolMetrics, "AAPL")
    msft = session.get(SymbolMetrics, "MSFT")
    assert aapl is not None
    assert aapl.sentiment_7d is not None
    assert msft is None or msft.sentiment_7d is None
    assert apply_news_sentiment_scored(session, scored) == "duplicate"


# --- company-name resolution -------------------------------------------------
#
# companies.json is not shipped in the API image. When it is missing the
# newsdata.io query used to degrade to the bare ticker, which materially
# changes what the provider returns, so the database is the dependable layer.


def test_company_name_map_falls_back_to_database_names(session, engine, monkeypatch, tmp_path):
    from stockviz.scheduler import company_name_map

    monkeypatch.setattr("stockviz.scheduler.engine", engine)
    monkeypatch.setattr("stockviz.scheduler.DEFAULT_COMPANIES_PATH", tmp_path / "missing.json")
    _symbol(session, "AAPL", name="Apple Inc.")

    assert company_name_map()["AAPL"] == "Apple Inc."


def test_company_name_map_prefers_the_seed_file_over_the_database(
    session, engine, monkeypatch, tmp_path
):
    import json

    from stockviz.scheduler import company_name_map

    monkeypatch.setattr("stockviz.scheduler.engine", engine)
    path = tmp_path / "companies.json"
    path.write_text(json.dumps([{"symbol": "AAPL", "name": "Apple Computer"}]), encoding="utf-8")
    monkeypatch.setattr("stockviz.scheduler.DEFAULT_COMPANIES_PATH", path)
    _symbol(session, "AAPL", name="Apple Inc.")

    assert company_name_map()["AAPL"] == "Apple Computer"
