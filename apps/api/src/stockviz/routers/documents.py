"""Company documents (A7.10, M5.5): list, read and search, point-in-time.

- `GET /v1/symbols/{t}/documents?kind=&as_of=`
- `GET /v1/documents/search?q=&ticker=&kind=&as_of=&limit=`
- `GET /v1/documents/passages?q=&ticker=&kind=&as_of=&limit=` (A8.4 hybrid search)
- `GET /v1/documents/{id}?q=`

Public and read-only like `/v1/news`. ``as_of`` (naive = UTC, default now)
hides every document not yet public then. Nothing here fetches.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Document, Symbol
from stockviz.models.document import DOCUMENT_KINDS
from stockviz.models.instrument import SCHEME_YAHOO, InstrumentIdentifier
from stockviz.schemas import (
    DocumentDetailOut,
    DocumentHitOut,
    DocumentListOut,
    DocumentOut,
    DocumentSearchOut,
    PassageOut,
    PassageSearchOut,
)
from stockviz.services.ai.embed import embedder_from_settings
from stockviz.services.documents import retrieve, store
from stockviz.services.instruments import instrument_ids
from stockviz.settings import get_settings

router = APIRouter(tags=["documents"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_TEXT_CHARS = 400_000
LIST_NOTE = (
    "Documents as stored: hand-placed files and, once configured, SEC EDGAR filings. "
    "Listed by when each became public; an assumed time is the end of its date in the "
    "venue's time zone."
)
SEARCH_NOTE = (
    "Exact phrase, case-insensitive, over the stored text of documents public by as_of. "
    "Not a semantic search."
)


def _naive(at: datetime | None) -> datetime:
    if at is None:
        return utcnow()
    if at.tzinfo is not None:
        return at.astimezone(UTC).replace(tzinfo=None)
    return at


def _kind(kind: str | None) -> str | None:
    if kind and kind not in DOCUMENT_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"kind must be one of {DOCUMENT_KINDS}")
    return kind or None


def _instrument(session: Session, ticker: str) -> tuple[str, int]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    ids = instrument_ids(session, [ticker])
    if ticker not in ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    return ticker, ids[ticker]


def _tickers(session: Session, instrument_ids_: set[int]) -> dict[int, str]:
    if not instrument_ids_:
        return {}
    rows = session.exec(
        select(InstrumentIdentifier.instrument_id, InstrumentIdentifier.value).where(
            col(InstrumentIdentifier.scheme) == SCHEME_YAHOO,
            col(InstrumentIdentifier.instrument_id).in_(sorted(instrument_ids_)),
            col(InstrumentIdentifier.valid_to).is_(None),
        )
    ).all()
    return dict(rows)


def _out(doc: Document, ticker: str) -> DocumentOut:
    assert doc.id is not None
    return DocumentOut(
        id=doc.id,
        ticker=ticker,
        kind=doc.kind,
        source=doc.source,
        form_type=doc.form_type,
        title=doc.title,
        event_date=doc.event_date,
        available_at=doc.available_at,
        available_assumed=doc.available_assumed,
        url=doc.url,
        content_type=doc.content_type,
        text_chars=doc.text_chars,
    )


@router.get("/v1/symbols/{ticker}/documents", response_model=DocumentListOut)
@limiter.limit("60/minute")
def symbol_documents(
    request: Request,
    ticker: str,
    session: SessionDep,
    kind: str | None = None,
    as_of: datetime | None = None,
) -> DocumentListOut:
    del request
    ticker, iid = _instrument(session, ticker)
    when = _naive(as_of)
    docs = store.list_documents(session, iid, as_of=when, kind=_kind(kind))
    return DocumentListOut(
        ticker=ticker, as_of=when, documents=[_out(d, ticker) for d in docs], note=LIST_NOTE
    )


@router.get("/v1/documents/search", response_model=DocumentSearchOut)
@limiter.limit("30/minute")
def search_documents(
    request: Request,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=store.MAX_QUERY_CHARS)],
    ticker: str | None = None,
    kind: str | None = None,
    as_of: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
) -> DocumentSearchOut:
    del request
    iid = _instrument(session, ticker)[1] if ticker else None
    when = _naive(as_of)
    hits = store.search(session, q, as_of=when, instrument_id=iid, kind=_kind(kind), limit=limit)
    names = _tickers(session, {h.document.instrument_id for h in hits})
    return DocumentSearchOut(
        query=q.strip(),
        as_of=when,
        hits=[
            DocumentHitOut(
                document=_out(h.document, names.get(h.document.instrument_id, "?")),
                matches=h.matches,
                snippets=h.snippets,
            )
            for h in hits
        ],
        note=SEARCH_NOTE,
    )


PASSAGE_METHOD = (
    "Passages of about 1,200 characters from documents public by as_of, ranked two ways: "
    "PostgreSQL full-text search and, when an embedding model is set, cosine similarity "
    "of embeddings; the two ranks are fused (reciprocal rank fusion, k = 60). Retrieval "
    "only: nothing here writes an answer."
)


@router.get("/v1/documents/passages", response_model=PassageSearchOut)
@limiter.limit("30/minute")
def search_passages(
    request: Request,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=retrieve.MAX_QUERY_CHARS)],
    ticker: str | None = None,
    kind: str | None = None,
    as_of: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> PassageSearchOut:
    del request
    iid = _instrument(session, ticker)[1] if ticker else None
    when = _naive(as_of)
    embedder = embedder_from_settings(get_settings())
    found = retrieve.retrieve(
        session, q, as_of=when, instrument_id=iid, kind=_kind(kind), limit=limit,
        embedder=embedder,
    )  # fmt: skip
    names = _tickers(session, {p.document.instrument_id for p in found.passages})
    return PassageSearchOut(
        query=found.query,
        as_of=when,
        mode=found.mode,
        embed_model=embedder.model if embedder else None,
        passages=[
            PassageOut(
                document=_out(p.document, names.get(p.document.instrument_id, "?")),
                chunk_id=p.chunk_id,
                position=p.position,
                start_char=p.start_char,
                end_char=p.end_char,
                text=p.text,
                score=p.score,
                keyword_rank=p.keyword_rank,
                vector_rank=p.vector_rank,
                similarity=p.similarity,
            )
            for p in found.passages
        ],
        notes=found.notes,
        method=PASSAGE_METHOD,
    )


@router.get("/v1/documents/{document_id}", response_model=DocumentDetailOut)
@limiter.limit("60/minute")
def get_document(
    request: Request,
    document_id: int,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=store.MAX_QUERY_CHARS)] = None,
) -> DocumentDetailOut:
    del request
    doc = session.get(Document, document_id)
    if doc is None or doc.available_at > utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    text = store.text_of(session, document_id)
    matches = None
    if q and q.strip():
        matches = len(re.findall(re.escape(q.strip()), text, flags=re.IGNORECASE))
    ticker = _tickers(session, {doc.instrument_id}).get(doc.instrument_id, "?")
    return DocumentDetailOut(
        document=_out(doc, ticker),
        text=text[:MAX_TEXT_CHARS],
        truncated=len(text) > MAX_TEXT_CHARS,
        matches=matches,
    )
