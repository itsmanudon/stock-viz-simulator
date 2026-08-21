"""Persistence, backfill, aggregation, and the sentiment endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import NewsArticle, Symbol, SymbolMetrics
from stockviz.models.sentiment import NewsSentiment
from stockviz.services.recommend.engine import score_ticker
from stockviz.services.sentiment.base import SentimentInput, SentimentScore
from stockviz.services.sentiment.store import (
    backfill_unscored,
    refresh_symbol_sentiment,
    score_articles,
)
from stockviz.settings import Settings


class StubProvider:
    """Returns a fixed score per call, and records what it was asked to score."""

    def __init__(self, score: float = 0.8, model: str = "stub-v1") -> None:
        self.name = model
        self._score = score
        self.seen: list[list[SentimentInput]] = []

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        self.seen.append(list(inputs))
        label = "positive" if self._score > 0.15 else "neutral"
        return [
            SentimentScore(label=label, score=self._score, model=self.name, confidence=0.9)
            for _ in inputs
        ]


def _article(
    session: Session,
    *,
    ticker: str,
    title: str,
    url: str,
    published_at: datetime | None = None,
    summary: str | None = None,
) -> NewsArticle:
    article = NewsArticle(
        ticker=ticker,
        title=title,
        url=url,
        source="test",
        published_at=published_at or utcnow(),
        summary=summary,
    )
    session.add(article)
    session.commit()
    session.refresh(article)
    return article


def _symbol(session: Session, ticker: str) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Co"))
    session.commit()


_SETTINGS = Settings(sentiment_provider="none")


# ---------------------------------------------------------------------------
# score_articles
# ---------------------------------------------------------------------------


def test_score_articles_persists_full_result(session: Session) -> None:
    _symbol(session, "AAPL")
    article = _article(session, ticker="AAPL", title="Good news", url="http://a/1")

    provider = StubProvider(score=0.75)
    assert score_articles(session, [article], provider=provider, settings=_SETTINGS) == 1

    row = session.exec(select(NewsSentiment)).one()
    assert row.article_id == article.id
    assert row.model == "stub-v1"
    assert row.label == "positive"
    assert row.score == Decimal("0.7500")
    assert row.confidence == Decimal("0.9000")

    # The denormalized badge column stays in step.
    session.refresh(article)
    assert article.sentiment == "positive"


def test_score_articles_sends_headline_and_summary(session: Session) -> None:
    _symbol(session, "AAPL")
    article = _article(
        session, ticker="AAPL", title="Acme beats", url="http://a/1", summary="Revenue up 12%."
    )
    provider = StubProvider()
    score_articles(session, [article], provider=provider, settings=_SETTINGS)

    text = provider.seen[0][0].as_text()
    assert "Acme beats" in text
    assert "Revenue up 12%." in text


def test_score_articles_dedupes_repeated_inputs(session: Session) -> None:
    """A URL appearing twice in one batch is dispatched once.

    Note: ``news_articles.url`` is globally unique, so the same story cannot
    exist as two rows under two tickers — this guards the cheaper case of a
    caller passing overlapping lists (e.g. per-ticker ingest batches that a
    future change merges together).
    """
    _symbol(session, "AAPL")
    article = _article(session, ticker="AAPL", title="Sector rally", url="http://shared/1")

    provider = StubProvider()
    score_articles(session, [article, article], provider=provider, settings=_SETTINGS)

    assert len(provider.seen[0]) == 1
    assert len(session.exec(select(NewsSentiment)).all()) == 1


def test_score_articles_upserts_on_rerun(session: Session) -> None:
    _symbol(session, "AAPL")
    article = _article(session, ticker="AAPL", title="News", url="http://a/1")

    score_articles(session, [article], provider=StubProvider(score=0.5), settings=_SETTINGS)
    score_articles(session, [article], provider=StubProvider(score=-0.5), settings=_SETTINGS)

    rows = session.exec(select(NewsSentiment)).all()
    assert len(rows) == 1
    assert rows[0].score == Decimal("-0.5000")


def test_two_models_coexist(session: Session) -> None:
    """Adding a model must not destroy the first model's history."""
    _symbol(session, "AAPL")
    article = _article(session, ticker="AAPL", title="News", url="http://a/1")

    score_articles(
        session, [article], provider=StubProvider(score=0.6, model="model-a"), settings=_SETTINGS
    )
    score_articles(
        session, [article], provider=StubProvider(score=-0.6, model="model-b"), settings=_SETTINGS
    )

    rows = session.exec(select(NewsSentiment)).all()
    assert {r.model for r in rows} == {"model-a", "model-b"}


def test_score_articles_respects_the_document_cap(session: Session) -> None:
    _symbol(session, "AAPL")
    articles = [
        _article(session, ticker="AAPL", title=f"N{i}", url=f"http://a/{i}") for i in range(5)
    ]
    provider = StubProvider()
    capped = Settings(sentiment_provider="none", sentiment_daily_document_cap=2)
    score_articles(session, articles, provider=provider, settings=capped)

    assert len(session.exec(select(NewsSentiment)).all()) == 2


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------


def test_backfill_scores_only_unscored_articles(session: Session) -> None:
    _symbol(session, "AAPL")
    old = _article(session, ticker="AAPL", title="Old", url="http://a/old")
    new = _article(session, ticker="AAPL", title="New", url="http://a/new")

    provider = StubProvider()
    score_articles(session, [old], provider=provider, settings=_SETTINGS)
    provider.seen.clear()

    written = backfill_unscored(session, provider=provider, settings=_SETTINGS)
    assert written == 1
    titles = [i.headline for i in provider.seen[0]]
    assert titles == ["New"]
    assert new.id is not None


def test_backfill_is_a_noop_without_a_provider(session: Session) -> None:
    """This is the production state today: nothing configured, nothing scored."""
    from stockviz.services.sentiment import NullProvider

    _symbol(session, "AAPL")
    _article(session, ticker="AAPL", title="News", url="http://a/1")
    assert backfill_unscored(session, provider=NullProvider(), settings=_SETTINGS) == 0


def test_backfill_respects_since_and_limit(session: Session) -> None:
    _symbol(session, "AAPL")
    now = utcnow()
    for i in range(5):
        _article(
            session,
            ticker="AAPL",
            title=f"N{i}",
            url=f"http://a/{i}",
            published_at=now - timedelta(days=i * 10),
        )

    provider = StubProvider()
    written = backfill_unscored(
        session,
        since=(now - timedelta(days=25)).date(),
        limit=2,
        provider=provider,
        settings=_SETTINGS,
    )
    assert written == 2


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def test_refresh_writes_the_rolling_mean(session: Session) -> None:
    _symbol(session, "AAPL")
    a = _article(session, ticker="AAPL", title="A", url="http://a/1")
    b = _article(session, ticker="AAPL", title="B", url="http://a/2")

    score_articles(session, [a], provider=StubProvider(score=1.0), settings=_SETTINGS)
    score_articles(session, [b], provider=StubProvider(score=0.0), settings=_SETTINGS)

    refresh_symbol_sentiment(session)
    metrics = session.get(SymbolMetrics, "AAPL")
    assert metrics is not None
    assert metrics.sentiment_7d == 0.5
    assert metrics.sentiment_article_count == 2


def test_symbol_without_scored_news_gets_null_not_zero(session: Session) -> None:
    """A gap in coverage is not a neutral reading — the screener must not
    treat silence as a signal."""
    _symbol(session, "QUIET")
    refresh_symbol_sentiment(session)

    metrics = session.get(SymbolMetrics, "QUIET")
    assert metrics is not None
    assert metrics.sentiment_7d is None
    assert metrics.sentiment_article_count == 0


def test_articles_outside_the_window_are_excluded(session: Session) -> None:
    _symbol(session, "AAPL")
    stale = _article(
        session,
        ticker="AAPL",
        title="Ancient",
        url="http://a/old",
        published_at=utcnow() - timedelta(days=60),
    )
    score_articles(session, [stale], provider=StubProvider(score=1.0), settings=_SETTINGS)

    refresh_symbol_sentiment(session, window_days=7)
    metrics = session.get(SymbolMetrics, "AAPL")
    assert metrics is not None
    assert metrics.sentiment_7d is None


# ---------------------------------------------------------------------------
# recommendation vote
# ---------------------------------------------------------------------------


def _flat_bars(n: int = 10) -> list[tuple[Decimal, int]]:
    return [(Decimal(100), 1_000) for _ in range(n)]


def test_sentiment_adds_a_vote_when_clearly_positive() -> None:
    without = score_ticker("AAPL", _flat_bars())
    with_pos = score_ticker("AAPL", _flat_bars(), sentiment_7d=0.8, sentiment_article_count=4)
    assert without is not None and with_pos is not None
    assert with_pos.score == without.score + 1
    assert any("news sentiment" in r for r in with_pos.rationale)


def test_sentiment_vote_needs_more_than_a_faint_signal() -> None:
    base = score_ticker("AAPL", _flat_bars())
    weak = score_ticker("AAPL", _flat_bars(), sentiment_7d=0.1, sentiment_article_count=4)
    assert base is not None and weak is not None
    assert weak.score == base.score


def test_no_scored_news_means_no_vote_not_a_penalty() -> None:
    base = score_ticker("AAPL", _flat_bars())
    none_scored = score_ticker("AAPL", _flat_bars(), sentiment_7d=None, sentiment_article_count=0)
    assert base is not None and none_scored is not None
    assert none_scored.score == base.score


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------


def test_sentiment_endpoint_returns_a_daily_series(session: Session, client: TestClient) -> None:
    _symbol(session, "AAPL")
    day = datetime(2026, 3, 2, 12, 0)
    a = _article(session, ticker="AAPL", title="A", url="http://a/1", published_at=day)
    b = _article(session, ticker="AAPL", title="B", url="http://a/2", published_at=day)
    score_articles(session, [a, b], provider=StubProvider(score=0.5), settings=_SETTINGS)

    response = client.get("/v1/symbols/AAPL/sentiment?days=365")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert len(body["points"]) == 1
    assert body["points"][0]["article_count"] == 2
    assert body["points"][0]["mean_score"] == 0.5


def test_sentiment_endpoint_404s_for_unknown_ticker(session: Session, client: TestClient) -> None:
    assert client.get("/v1/symbols/NOPE/sentiment").status_code == 404


def test_sentiment_endpoint_is_empty_when_nothing_is_scored(
    session: Session, client: TestClient
) -> None:
    _symbol(session, "AAPL")
    _article(session, ticker="AAPL", title="A", url="http://a/1")

    body = client.get("/v1/symbols/AAPL/sentiment").json()
    assert body["points"] == []
    assert body["rolling_7d"] is None
