"""News, sentiment and the signals vote read Aegis since Phase 2 (AG-14, SR-9)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz import cli
from stockviz._time import utcnow
from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    NewsArticle,
    Recommendation,
    Symbol,
    SymbolMetrics,
)
from stockviz.services.aegis.read import refresh_aegis_sentiment
from stockviz.services.recommend.engine import max_score, score_ticker

ENTITY = {"AAPL": "ent_apple", "MSFT": "ent_msft"}


def _symbols(session: Session) -> None:
    for ticker in ("AAPL", "MSFT", "TSLA"):
        session.add(Symbol(ticker=ticker, name=f"{ticker} Inc."))
    for ticker, entity in ENTITY.items():
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}",
                entity_id=entity,
                scheme="provider_id",
                identifier=f"stockviz:{ticker}",
                created_at=datetime(2026, 11, 1),
            )
        )
    session.commit()


def _document(
    session: Session,
    doc_id: str,
    *,
    tickers: list[str],
    available_at: datetime,
    sentiment: tuple[str, float] | None = None,
    published_at: datetime | None = None,
    entities: list[str] | None = None,
) -> None:
    session.add(
        AegisDocument(
            document_id=doc_id,
            source_id="src_1",
            source_name="Reuters",
            title=f"Headline {doc_id}",
            url=f"https://news.example.test/{doc_id}",
            published_at=published_at,
            first_seen_at=available_at,
            available_at=available_at,
            last_signed_at=available_at,
        )
    )
    session.flush()
    for entity in entities if entities is not None else [ENTITY[t] for t in tickers]:
        session.add(
            AegisDocumentEntity(
                document_id=doc_id,
                entity_id=entity,
                canonical_name=entity,
                kind="organization",
                resolution_analysis_id=f"ana_res_{doc_id}",
                confidence=1.0,
            )
        )
    if sentiment is not None:
        label, score = sentiment
        session.add(
            AegisAnalysis(
                analysis_id=f"ana_sent_{doc_id}",
                document_id=doc_id,
                analysis_type="sentiment",
                provider="local-baseline",
                model_name="lexicon-sentiment",
                model_version="1",
                configuration_hash="0" * 64,
                available_at=available_at,
                label=label,
                score=score,
                outputs=[{"label": label, "score": score}],
            )
        )
    session.commit()


# ---------------------------------------------------------------------------
# /v1/symbols/{ticker}/news and /v1/news
# ---------------------------------------------------------------------------


def test_ticker_news_reads_aegis_newest_available_first(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    now = utcnow()
    _document(session, "doc_old", tickers=["AAPL"], available_at=now - timedelta(days=2))
    _document(
        session,
        "doc_new",
        tickers=["AAPL", "MSFT"],
        available_at=now - timedelta(hours=1),
        sentiment=("mixed", 0.05),
        # A publisher date later than another document's does not reorder: the
        # feed orders by when Aegis knew it (AG-12).
        published_at=now - timedelta(days=5),
    )
    _document(session, "doc_msft", tickers=["MSFT"], available_at=now)
    # Legacy rows are no longer read.
    session.add(NewsArticle(ticker="AAPL", title="Legacy", url="https://x", published_at=now))
    session.commit()

    response = client.get("/v1/symbols/aapl/news")
    assert response.status_code == 200
    body = response.json()
    assert [a["id"] for a in body] == ["doc_new", "doc_old"]
    first = body[0]
    assert first["tickers"] == ["AAPL", "MSFT"]
    assert first["sentiment"] == "mixed"
    assert first["sentiment_model"] == "lexicon-sentiment@1"
    assert first["source"] == "Reuters"
    assert first["url"] == "https://news.example.test/doc_new"
    assert set(first) >= {"available_at", "published_at"}
    # No article text or images, ever.
    assert "summary" not in first and "image_url" not in first
    assert body[1]["sentiment"] is None and body[1]["published_at"] is None


def test_ticker_news_404s_for_an_unknown_symbol(client: TestClient) -> None:
    assert client.get("/v1/symbols/NOPE/news").status_code == 404


def test_latest_news_lists_only_documents_linked_to_a_symbol(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    now = utcnow()
    _document(session, "doc_linked", tickers=["AAPL"], available_at=now)
    _document(session, "doc_unmapped", tickers=[], entities=["ent_unknown"], available_at=now)

    assert [a["id"] for a in client.get("/v1/news").json()] == ["doc_linked"]


# ---------------------------------------------------------------------------
# /v1/symbols/{ticker}/sentiment
# ---------------------------------------------------------------------------


def test_sentiment_series_buckets_by_when_aegis_knew_the_score(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    day = (utcnow() - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
    _document(session, "d1", tickers=["AAPL"], available_at=day, sentiment=("positive", 0.6))
    _document(session, "d2", tickers=["AAPL"], available_at=day, sentiment=("negative", -0.2))
    _document(
        session,
        "d3",
        tickers=["AAPL"],
        available_at=day + timedelta(days=1),
        sentiment=("neutral", 0.0),
        published_at=day - timedelta(days=30),
    )

    body = client.get("/v1/symbols/AAPL/sentiment?days=30").json()
    assert [(p["date"], p["article_count"]) for p in body["points"]] == [
        (day.date().isoformat(), 2),
        ((day + timedelta(days=1)).date().isoformat(), 1),
    ]
    assert abs(body["points"][0]["mean_score"] - 0.2) < 1e-9


# ---------------------------------------------------------------------------
# sentiment_7d, the vote and the screener filter (AG-14, SR-9)
# ---------------------------------------------------------------------------


def test_rolling_sentiment_comes_from_aegis_inside_the_week(session: Session) -> None:
    _symbols(session)
    now = datetime(2026, 11, 11, 22, 0)
    _document(
        session,
        "in1",
        tickers=["AAPL"],
        available_at=now - timedelta(days=1),
        sentiment=("positive", 0.5),
    )
    _document(
        session,
        "in2",
        tickers=["AAPL"],
        available_at=now - timedelta(days=6),
        sentiment=("positive", 0.3),
    )
    _document(
        session,
        "old",
        tickers=["AAPL"],
        available_at=now - timedelta(days=8),
        sentiment=("negative", -0.9),
    )
    # Known only after "now": invisible to a point-in-time read.
    _document(
        session,
        "future",
        tickers=["AAPL"],
        available_at=now + timedelta(hours=1),
        sentiment=("negative", -0.9),
    )
    # One document linked to two symbols counts once for each.
    _document(
        session,
        "both",
        tickers=["AAPL", "MSFT"],
        available_at=now - timedelta(days=2),
        sentiment=("mixed", 0.1),
    )

    assert refresh_aegis_sentiment(session, now=now) == 3

    aapl = session.get(SymbolMetrics, "AAPL")
    msft = session.get(SymbolMetrics, "MSFT")
    tsla = session.get(SymbolMetrics, "TSLA")
    assert aapl is not None and msft is not None and tsla is not None
    assert aapl.sentiment_article_count == 3
    assert abs((aapl.sentiment_7d or 0) - 0.3) < 1e-9
    assert msft.sentiment_article_count == 1 and abs((msft.sentiment_7d or 0) - 0.1) < 1e-9
    # No signal is NULL, not neutral.
    assert tsla.sentiment_7d is None and tsla.sentiment_article_count == 0


def test_the_sentiment_vote_is_unavailable_without_scored_news() -> None:
    bars = [(Decimal(100 + i), 1_000 + i) for i in range(30)]
    without = score_ticker("AAPL", bars)
    with_news = score_ticker("AAPL", bars, sentiment_7d=0.5, sentiment_article_count=3)
    assert without is not None and with_news is not None
    assert max_score(without.votes) == 6
    assert max_score(with_news.votes) == 7
    vote = next(v for v in without.votes if v.id == "positive_sentiment")
    assert vote.available is False and vote.as_dict()["available"] is False


def test_recommendations_report_the_maximum_that_could_pass(
    session: Session, client: TestClient
) -> None:
    _symbols(session)
    bars = [(Decimal(100 + i), 1_000 + i) for i in range(30)]
    result = score_ticker("AAPL", bars)
    assert result is not None
    session.add(
        Recommendation(
            ticker="AAPL",
            score=Decimal(result.score),
            rationale="; ".join(result.rationale) or None,
            votes=[v.as_dict() for v in result.votes],
        )
    )
    # A row written before the flag existed reads as seven available votes.
    old_votes = [v.as_dict() for v in result.votes]
    for vote in old_votes:
        vote.pop("available")
    session.add(Recommendation(ticker="MSFT", score=Decimal(3), rationale=None, votes=old_votes))
    session.commit()

    rows = {r["ticker"]: r for r in client.get("/v1/recommendations").json()}
    assert rows["AAPL"]["max_score"] == 6
    assert rows["MSFT"]["max_score"] == 7
    sentiment_vote = next(v for v in rows["AAPL"]["votes"] if v["id"] == "positive_sentiment")
    assert sentiment_vote["available"] is False


def test_cli_sentiment_aggregate_uses_aegis(engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "engine", engine)
    with Session(engine) as session:
        _symbols(session)
        _document(
            session,
            "d",
            tickers=["AAPL"],
            available_at=utcnow() - timedelta(hours=2),
            sentiment=("positive", 0.4),
        )

    assert cli.main(["sentiment-aggregate"]) == 0
    assert "Aegis" in capsys.readouterr().out
    with Session(engine) as session:
        metrics = session.get(SymbolMetrics, "AAPL")
        assert metrics is not None and metrics.sentiment_article_count == 1


def test_latest_news_filters_to_a_set_of_tickers(session: Session, client: TestClient) -> None:
    """The watchlist and portfolio pages ask for their own symbols (Phase 2)."""
    _symbols(session)
    now = utcnow()
    _document(session, "doc_aapl", tickers=["AAPL"], available_at=now - timedelta(hours=2))
    _document(session, "doc_both", tickers=["AAPL", "MSFT"], available_at=now - timedelta(hours=1))
    _document(session, "doc_msft", tickers=["MSFT"], available_at=now)

    ids = lambda q: [a["id"] for a in client.get(f"/v1/news?{q}").json()]  # noqa: E731
    assert ids("tickers=aapl") == ["doc_both", "doc_aapl"]
    # A document linked to two requested symbols appears once.
    assert ids("tickers=AAPL,%20msft") == ["doc_msft", "doc_both", "doc_aapl"]
    assert ids("tickers=TSLA") == []
    assert ids("tickers=,") == []
    assert ids("tickers=AAPL&limit=1") == ["doc_both"]
