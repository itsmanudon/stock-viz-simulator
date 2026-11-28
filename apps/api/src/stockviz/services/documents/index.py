"""Build the search index of documents: chunks, then embeddings (A8.4, M11.1).

``index_documents`` chunks every document that has none (new documents are
chunked when stored), then, with an embedder, embeds every passage that has no
vector from that model (from ``embed_input``: the A8.8 context line, then the
text). Writes only to the local database (``docs-index``).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, col, func, select

from stockviz.models import Document, DocumentChunk
from stockviz.services.ai.embed import Embedder
from stockviz.services.documents.chunks import build_chunks

EMBED_BATCH = 64


def embed_input(chunk: DocumentChunk) -> str:
    """What a passage is embedded from: its A8.8 context line, then its text."""
    return f"{chunk.context}\n{chunk.text}" if chunk.context else chunk.text


@dataclass
class IndexReport:
    documents_chunked: int = 0
    chunks_added: int = 0
    chunks_embedded: int = 0
    chunks_waiting: int = 0
    model: str | None = None


def unchunked_document_ids(session: Session) -> list[int]:
    has = select(DocumentChunk.document_id).distinct()
    rows = session.exec(
        select(col(Document.id)).where(col(Document.id).not_in(has)).order_by(col(Document.id))
    ).all()
    return [int(i) for i in rows if i is not None]


def index_documents(
    session: Session, *, embedder: Embedder | None = None, max_embed: int | None = None
) -> IndexReport:
    report = IndexReport(model=embedder.model if embedder else None)
    for doc_id in unchunked_document_ids(session):
        report.chunks_added += build_chunks(session, doc_id)
        report.documents_chunked += 1
    session.commit()
    if embedder is None:
        report.chunks_waiting = session.exec(select(func.count()).select_from(DocumentChunk)).one()
        return report
    pending = select(DocumentChunk).where(
        (col(DocumentChunk.embed_model).is_(None))
        | (col(DocumentChunk.embed_model) != embedder.model)
    )
    while max_embed is None or report.chunks_embedded < max_embed:
        size = (
            EMBED_BATCH
            if max_embed is None
            else min(EMBED_BATCH, max_embed - report.chunks_embedded)
        )
        batch = list(session.exec(pending.order_by(col(DocumentChunk.id)).limit(size)).all())
        if not batch:
            break
        vectors = embedder.embed([embed_input(c) for c in batch], "document")
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embed_model = embedder.model
            session.add(chunk)
        session.commit()
        report.chunks_embedded += len(batch)
    report.chunks_waiting = session.exec(select(func.count()).select_from(pending.subquery())).one()
    return report
