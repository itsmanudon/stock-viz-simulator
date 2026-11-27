"""Write and read documents (A7.10).

``add_document`` dedupes on the source bytes' SHA-256: the same file or filing
returns the stored row (``created=False``). A new document is chunked for
hybrid search (A8.4) in the same transaction; embeddings come later. Reads are point-in-time: a
document counts only once ``available_at <= as_of``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.models import Document, DocumentText
from stockviz.services.documents.chunks import build_chunks
from stockviz.services.documents.extract import Extracted

SNIPPET_CHARS = 90
MAX_QUERY_CHARS = 100


@dataclass(frozen=True)
class NewDocument:
    instrument_id: int
    kind: str
    source: str
    title: str
    available_at: datetime
    available_assumed: bool = False
    event_date: date | None = None
    form_type: str | None = None
    url: str | None = None
    accession: str | None = None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_by_hash(session: Session, digest: str) -> Document | None:
    return session.exec(select(Document).where(Document.sha256 == digest)).first()


def add_document(
    session: Session, meta: NewDocument, data: bytes, extracted: Extracted
) -> tuple[Document, bool]:
    digest = sha256_of(data)
    existing = find_by_hash(session, digest)
    if existing is not None:
        return existing, False
    doc = Document(
        instrument_id=meta.instrument_id,
        kind=meta.kind,
        source=meta.source,
        form_type=meta.form_type,
        title=meta.title[:300],
        event_date=meta.event_date,
        available_at=meta.available_at,
        available_assumed=meta.available_assumed,
        url=meta.url,
        accession=meta.accession,
        sha256=digest,
        content_type=extracted.content_type,
        size_bytes=len(data),
        text_chars=len(extracted.text),
    )
    session.add(doc)
    session.flush()
    assert doc.id is not None
    session.add(DocumentText(document_id=doc.id, text=extracted.text))
    build_chunks(session, doc.id, extracted.text)
    return doc, True


def list_documents(
    session: Session,
    instrument_id: int,
    *,
    as_of: datetime,
    kind: str | None = None,
    limit: int = 100,
) -> list[Document]:
    query = select(Document).where(
        Document.instrument_id == instrument_id, col(Document.available_at) <= as_of
    )
    if kind:
        query = query.where(Document.kind == kind)
    query = query.order_by(col(Document.available_at).desc(), col(Document.id).desc())
    return list(session.exec(query.limit(limit)).all())


def text_of(session: Session, document_id: int) -> str:
    row = session.get(DocumentText, document_id)
    return row.text if row else ""


def snippets(text: str, query: str, *, limit: int = 3) -> list[str]:
    """Up to ``limit`` passages around case-insensitive matches of ``query``."""
    if not query:
        return []
    out: list[str] = []
    for m in re.finditer(re.escape(query), text, flags=re.IGNORECASE):
        start = max(0, m.start() - SNIPPET_CHARS)
        end = min(len(text), m.end() + SNIPPET_CHARS)
        piece = " ".join(text[start:end].split())
        out.append(("…" if start else "") + piece + ("…" if end < len(text) else ""))
        if len(out) >= limit:
            break
    return out


@dataclass(frozen=True)
class SearchHit:
    document: Document
    matches: int
    snippets: list[str]


def search(
    session: Session,
    query: str,
    *,
    as_of: datetime,
    instrument_id: int | None = None,
    kind: str | None = None,
    limit: int = 25,
) -> list[SearchHit]:
    """Documents whose text holds ``query`` (case-insensitive), newest first."""
    q = query.strip()[:MAX_QUERY_CHARS]
    if not q:
        return []
    stmt = (
        select(Document, DocumentText.text)
        .join(DocumentText, col(DocumentText.document_id) == col(Document.id))
        .where(
            col(Document.available_at) <= as_of,
            func.lower(DocumentText.text).contains(q.lower(), autoescape=True),
        )
    )
    if instrument_id is not None:
        stmt = stmt.where(Document.instrument_id == instrument_id)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    stmt = stmt.order_by(col(Document.available_at).desc(), col(Document.id).desc()).limit(limit)
    hits: list[SearchHit] = []
    for doc, text in session.exec(stmt).all():
        count = len(re.findall(re.escape(q), text, flags=re.IGNORECASE))
        hits.append(SearchHit(doc, count, snippets(text, q)))
    return hits
