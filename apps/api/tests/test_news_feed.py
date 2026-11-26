"""`/v1/news/feed` and `/v1/news/overview` (news redesign, 26 Nov 2026)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session

from stockviz.models import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    PriceBar,
    Symbol,
)
from stockviz.services.aegis import feed as news_feed

ENTITY = {"AAPL": "ent_apple", "MSFT": "ent_msft"}


def _symbols(session: Session) -> None:
    for ticker in ("AAPL", "MSFT"):
        session.add(Symbol(ticker=ticker, name=f"{ticker} Inc."))
        session.add(
            AegisMapping(
                mapping_id=f"map_{ticker}",
                entity_id=ENTITY[ticker],
                scheme="provider_id",
                identifier=f"stockviz:{ticker}",
                created_at=datetime(2026, 11, 1),
            )
        )
    session.commit()


def _analysis(session: Session, doc_id: str, kind: str, label: str, at: datetime) -> None:
    session.add(
        AegisAnalysis(
            analysis_id=f"ana_{kind}_{doc_id}",
            document_id=doc_id,
            analysis_type=kind,
            provider="local-baseline",
            model_name="lexicon",
            model_version="1",
            configuration_hash="0" * 64,
            available_at=at,
            label=label,
            score=0.5,
            outputs=[],
        )
    )


def _doc(
    session: Session,
    doc_id: str,
    at: datetime,
    *,
    tickers: tuple[str, ...] = (),
    title: str | None = None,
    source: str = "Reuters",
    sentiment: str | None = None,
    topic: str | None = None,
) -> None:
    session.add(
        AegisDocument(
            document_id=doc_id,
            source_id=f"src_{source}",
            source_name=source,
            title=title or f"Headline {doc_id}",
            url=f"https://news.example.test/{doc_id}",
            first_seen_at=at,
            available_at=at,
            last_signed_at=at,
        )
    )
    session.flush()
    for ticker in tickers:
        session.add(
            AegisDocumentEntity(
                document_id=doc_id,
                entity_id=ENTITY[ticker],
                canonical_name=ticker,
                kind="organization",
                resolution_analysis_id=f"res_{doc_id}",
                confidence=1.0,
            )
        )
    if sentiment:
        _analysis(session, doc_id, "sentiment", sentiment, at)
    if topic:
        _analysis(session, doc_id, "topic", topic, at)
    session.commit()


def _bars(session: Session, ticker: str, closes: list[float], start: date) -> list[date]:
    day, dates = start, []
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        session.add(PriceBar(ticker=ticker, ts=datetime.combine(day, datetime.min.time()),
                             interval="1d", open=Decimal(str(close)), high=Decimal(str(close)),
                             low=Decimal(str(close)), close=Decimal(str(close)), volume=1000,
                             source="test"))  # fmt: skip
        dates.append(day)
        day += timedelta(days=1)
    session.commit()
    return dates


def _archive(session: Session) -> None:
    _symbols(session)
    base = datetime(2026, 11, 2, 12)
    _doc(session, "a1", base, tickers=("AAPL",), title="Apple beats on iPhone sales",
         sentiment="positive", topic="earnings")  # fmt: skip
    _doc(session, "a2", base + timedelta(days=1), tickers=("AAPL", "MSFT"),
         title="Apple and Microsoft face EU probe", source="Bloomberg", sentiment="negative",
         topic="regulation")  # fmt: skip
    _doc(session, "m1", base + timedelta(days=2), tickers=("MSFT",),
         title="Microsoft cloud growth slows", sentiment="mixed")  # fmt: skip
    _doc(session, "x1", base + timedelta(days=2, hours=1), title="Fed holds rates steady",
         source="AP")  # fmt: skip


def test_feed_pages_through_the_whole_archive_with_a_cursor(session, client) -> None:
    _symbols(session)
    start = datetime(2026, 1, 1)
    for n in range(130):
        _doc(session, f"d{n:03d}", start + timedelta(hours=n), tickers=("AAPL",))
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 50, **({"cursor": cursor} if cursor else {})}
        body = client.get("/v1/news/feed", params=params).json()
        assert body["total"] == 130
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 130 == len(set(seen))
    assert seen[0] == "d129" and seen[-1] == "d000"


def test_ties_on_available_at_page_by_document_id(session, client) -> None:
    _symbols(session)
    at = datetime(2026, 3, 3, 9)
    for doc in ("b", "a", "c"):
        _doc(session, doc, at, tickers=("AAPL",))
    first = client.get("/v1/news/feed", params={"limit": 2}).json()
    rest = client.get("/v1/news/feed", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["id"] for i in first["items"]] + [i["id"] for i in rest["items"]] == ["a", "b", "c"]


def test_filters_narrow_the_feed_and_the_total(session, client) -> None:
    _archive(session)

    def ids(**params) -> list[str]:
        body = client.get("/v1/news/feed", params=params).json()
        assert body["total"] == len(body["items"])
        return [i["id"] for i in body["items"]]

    assert ids() == ["m1", "a2", "a1"]  # symbols scope by default
    assert ids(scope="market") == ["x1"]
    assert ids(scope="all") == ["x1", "m1", "a2", "a1"]
    assert ids(tickers="msft") == ["m1", "a2"]
    assert ids(q="apple probe") == ["a2"]  # every word must appear
    assert ids(q="APPLE") == ["a2", "a1"]  # case ignored
    assert ids(sentiment="positive,mixed") == ["m1", "a1"]
    assert ids(scope="all", sentiment="unscored") == ["x1"]
    assert ids(topic="regulation") == ["a2"]
    assert ids(source="Bloomberg") == ["a2"]
    assert ids(**{"from": "2026-11-03", "to": "2026-11-03"}) == ["a2"]


def test_feed_carries_tickers_labels_and_no_article_text(session, client) -> None:
    _archive(session)
    item = client.get("/v1/news/feed", params={"q": "probe"}).json()["items"][0]
    assert item["tickers"] == ["AAPL", "MSFT"]
    assert item["sentiment"] == "negative" and item["topic"] == "regulation"
    assert item["source"] == "Bloomberg" and item["url"].endswith("/a2")
    assert not {"body", "text", "summary", "content"} & set(item)


def test_reaction_is_the_session_after_the_headline(session, client) -> None:
    _symbols(session)
    dates = _bars(session, "AAPL", [100, 101, 102, 110, 111, 112, 113], date(2026, 11, 2))
    # Monday 2 Nov at 15:00 UTC is before the New York close: Monday reacts.
    _doc(session, "pre", datetime(2026, 11, 2, 15), tickers=("AAPL",))
    # Tuesday 3 Nov at 23:00 UTC is after it: Wednesday reacts.
    _doc(session, "post", datetime(2026, 11, 3, 23), tickers=("AAPL",))
    items = {i["id"]: i for i in client.get("/v1/news/feed").json()["items"]}

    pre = items["pre"]["reactions"][0]
    assert pre["session_date"] == dates[0].isoformat()
    assert pre["change_pct"] is None  # no earlier close held
    assert pre["closes"][pre["reaction_index"]] == 100

    post = items["post"]["reactions"][0]
    assert post["ticker"] == "AAPL"
    assert post["session_date"] == dates[2].isoformat()
    assert post["change_pct"] == round((102 / 101 - 1) * 100, 2)
    assert post["closes"][post["reaction_index"]] == 102
    assert len(post["closes"]) <= 2 * news_feed.REACTION_BARS + 1


def test_no_reaction_without_a_later_session(session, client) -> None:
    _symbols(session)
    _bars(session, "AAPL", [100, 101], date(2026, 11, 2))
    _doc(session, "late", datetime(2026, 11, 20, 12), tickers=("AAPL",))
    assert client.get("/v1/news/feed").json()["items"][0]["reactions"] == []


def test_overview_timeline_facets_and_heatmap(session, client) -> None:
    _archive(session)
    body = client.get("/v1/news/overview", params={"scope": "all"}).json()
    assert body["total"] == 4
    assert body["first_date"] == "2026-11-02" and body["last_date"] == "2026-11-04"
    assert [d["date"] for d in body["days"]] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert body["days"][2] == {"date": "2026-11-04", "positive": 0, "neutral": 0,
                               "negative": 0, "mixed": 1, "unscored": 1}  # fmt: skip
    assert body["sentiments"] == {"positive": 1, "neutral": 0, "negative": 1,
                                  "mixed": 1, "unscored": 1}  # fmt: skip
    assert {f["value"]: f["count"] for f in body["sources"]} == {
        "Reuters": 2, "Bloomberg": 1, "AP": 1}  # fmt: skip
    assert {f["value"] for f in body["topics"]} == {"earnings", "regulation"}

    assert len(body["heatmap_days"]) == news_feed.HEATMAP_DAYS
    assert body["heatmap_days"][-1] == "2026-11-04"
    rows = {r["ticker"]: r for r in body["heatmap"]}
    assert rows["AAPL"]["total"] == 2 and rows["MSFT"]["total"] == 2
    aapl = {c["date"]: c for c in rows["AAPL"]["cells"]}
    assert aapl["2026-11-02"] == {"date": "2026-11-02", "count": 1, "net": 1.0}
    assert aapl["2026-11-03"]["net"] == -1.0
    assert aapl["2026-11-04"] == {"date": "2026-11-04", "count": 0, "net": None}


def test_overview_timeline_ignores_dates_but_counts_honour_them(session, client) -> None:
    _archive(session)
    body = client.get("/v1/news/overview", params={"from": "2026-11-03", "to": "2026-11-03"}).json()
    assert len(body["days"]) == 3  # the whole archive, to brush on
    assert body["total"] == 1
    assert body["sentiments"]["negative"] == 1 and body["sentiments"]["positive"] == 0


def test_an_empty_archive_is_an_empty_overview(client) -> None:
    body = client.get("/v1/news/overview").json()
    assert body["total"] == 0 and body["days"] == [] and body["heatmap"] == []


def test_bad_requests(session, client) -> None:
    _archive(session)
    assert client.get("/v1/news/feed", params={"cursor": "not-ours"}).status_code == 400
    assert client.get("/v1/news/feed", params={"sentiment": "bullish"}).status_code == 400
    bad_range = client.get("/v1/news/feed", params={"from": "2026-11-05", "to": "2026-11-01"})
    assert bad_range.status_code == 400
    market = client.get("/v1/news/feed", params={"scope": "market", "tickers": "AAPL"})
    assert market.status_code == 400


def test_like_wildcards_in_the_query_are_literal(session, client) -> None:
    _symbols(session)
    _doc(session, "pct", datetime(2026, 5, 1), tickers=("AAPL",), title="Shares up 5% today")
    _doc(session, "plain", datetime(2026, 5, 2), tickers=("AAPL",), title="Shares up 5 today")
    ids = [i["id"] for i in client.get("/v1/news/feed", params={"q": "5%"}).json()["items"]]
    assert ids == ["pct"]
