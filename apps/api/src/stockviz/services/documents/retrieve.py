"""Hybrid passage retrieval over documents (A8.4, M11.1).

Two rankings of the passages (``document_chunks``) of documents public by
``as_of``, fused with reciprocal rank fusion (``1 / (RRF_K + rank)`` summed):

- **keyword**: PostgreSQL full text, ``ts_rank_cd`` of
  ``to_tsvector('english', text)`` against ``websearch_to_tsquery`` (quotes,
  ``or`` and ``-word`` work as on a web search box); on SQLite (tests only) a
  plain term count stands in, with no stemming;
- **vector**: cosine similarity of the query's embedding to each passage
  embedded with the same model, computed in Python with NumPy (no pgvector).

With no embedder, or when Ollama fails, the result is keyword only and says
why. Passages without an embedding from the current model take no part in the
vector ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import func, literal_column
from sqlmodel import Session, col, select

from stockviz.models import Document, DocumentChunk
from stockviz.services.ai.embed import Embedder
from stockviz.services.ai.provider import AiProviderError

RRF_K = 60
CANDIDATES = 50
MAX_VECTOR_PASSAGES = 20_000
MAX_QUERY_CHARS = 300


@dataclass(frozen=True)
class Passage:
    document: Document
    chunk_id: int
    position: int
    start_char: int
    end_char: int
    text: str
    score: float
    keyword_rank: int | None
    vector_rank: int | None
    similarity: float | None


@dataclass
class Retrieval:
    query: str
    mode: str  # hybrid | keyword
    passages: list[Passage]
    notes: list[str] = field(default_factory=list)


def _filters(stmt, as_of: datetime, instrument_id: int | None, kind: str | None):
    stmt = stmt.where(col(Document.available_at) <= as_of)
    if instrument_id is not None:
        stmt = stmt.where(Document.instrument_id == instrument_id)
    if kind:
        stmt = stmt.where(Document.kind == kind)
    return stmt


STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "with",
        "how",
        "does",
    ]
)


def _sqlite_keyword_ranking(
    session: Session, query: str, *, as_of: datetime, instrument_id: int | None, kind: str | None
) -> list[int]:
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    terms = [t for t in terms if t not in STOPWORDS]
    if not terms:
        return []
    stmt = select(col(DocumentChunk.id), col(DocumentChunk.text)).join(
        Document, col(Document.id) == col(DocumentChunk.document_id)
    )
    scored = []
    for cid, text in session.exec(_filters(stmt, as_of, instrument_id, kind)).all():
        low = text.lower()
        hits = [len(re.findall(rf"\b{re.escape(t)}", low)) for t in terms]
        if any(hits):
            scored.append((-(sum(1 for h in hits if h) * 100 + sum(hits)), cid))
    return [cid for _, cid in sorted(scored)[:CANDIDATES] if cid is not None]


def keyword_ranking(
    session: Session, query: str, *, as_of: datetime, instrument_id: int | None, kind: str | None
) -> list[int]:
    if session.get_bind().dialect.name == "sqlite":
        return _sqlite_keyword_ranking(
            session, query, as_of=as_of, instrument_id=instrument_id, kind=kind
        )
    tsq = func.websearch_to_tsquery("english", query)
    tsv = func.to_tsvector(literal_column("'english'"), col(DocumentChunk.text))
    rank = func.ts_rank_cd(tsv, tsq)
    stmt = (
        select(col(DocumentChunk.id))
        .join(Document, col(Document.id) == col(DocumentChunk.document_id))
        .where(tsv.op("@@")(tsq))
    )
    stmt = _filters(stmt, as_of, instrument_id, kind)
    stmt = stmt.order_by(rank.desc(), col(DocumentChunk.id)).limit(CANDIDATES)
    return [int(i) for i in session.exec(stmt).all() if i is not None]


def vector_ranking(
    session: Session,
    query_vector: list[float],
    model: str,
    *,
    as_of: datetime,
    instrument_id: int | None,
    kind: str | None,
) -> tuple[list[tuple[int, float]], bool]:
    """(chunk id, cosine) best first, and whether the passage cap cut the pool."""
    stmt = (
        select(col(DocumentChunk.id), col(DocumentChunk.embedding))
        .join(Document, col(Document.id) == col(DocumentChunk.document_id))
        .where(col(DocumentChunk.embed_model) == model, col(DocumentChunk.embedding).is_not(None))
    )
    stmt = _filters(stmt, as_of, instrument_id, kind)
    stmt = stmt.order_by(col(Document.available_at).desc(), col(DocumentChunk.id)).limit(
        MAX_VECTOR_PASSAGES + 1
    )
    rows = [(i, v) for i, v in session.exec(stmt).all() if i is not None and v]
    capped = len(rows) > MAX_VECTOR_PASSAGES
    rows = rows[:MAX_VECTOR_PASSAGES]
    q = np.asarray(query_vector, dtype=np.float32)
    rows = [(i, v) for i, v in rows if len(v) == len(q)]
    if not rows or not np.any(q):
        return [], capped
    m = np.asarray([v for _, v in rows], dtype=np.float32)
    norms = np.linalg.norm(m, axis=1) * float(np.linalg.norm(q))
    sims = np.divide(m @ q, norms, out=np.zeros(len(rows), dtype=np.float32), where=norms > 0)
    order = np.argsort(-sims, kind="stable")[:CANDIDATES]
    return [(int(rows[k][0]), float(sims[k])) for k in order], capped


def retrieve(
    session: Session,
    query: str,
    *,
    as_of: datetime,
    instrument_id: int | None = None,
    kind: str | None = None,
    limit: int = 8,
    embedder: Embedder | None = None,
) -> Retrieval:
    q = " ".join(query.split())[:MAX_QUERY_CHARS]
    out = Retrieval(query=q, mode="keyword", passages=[])
    if not q:
        return out
    keyword = keyword_ranking(session, q, as_of=as_of, instrument_id=instrument_id, kind=kind)
    vector: list[tuple[int, float]] = []
    if embedder is None:
        out.notes.append("Keyword only: no embedding model is set (OLLAMA_EMBED_MODEL).")
    else:
        try:
            (qv,) = embedder.embed([q], "query")
            vector, capped = vector_ranking(
                session, qv, embedder.model, as_of=as_of, instrument_id=instrument_id, kind=kind
            )
            out.mode = "hybrid"
            if capped:
                out.notes.append(
                    f"Vector ranking read the newest {MAX_VECTOR_PASSAGES:,} passages only."
                )
            if not vector:
                out.notes.append(
                    f"No passage is embedded with {embedder.model} yet (run docs-index --embed)."
                )
        except AiProviderError as exc:
            out.notes.append(f"Keyword only: the embedding call failed ({exc}).")
    scores: dict[int, float] = {}
    k_rank = {cid: r for r, cid in enumerate(keyword, start=1)}
    v_rank = {cid: r for r, (cid, _) in enumerate(vector, start=1)}
    sims = dict(vector)
    for cid, r in k_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + r)
    for cid, r in v_rank.items():
        scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + r)
    best = sorted(scores, key=lambda c: (-scores[c], c))[:limit]
    if not best:
        return out
    rows = session.exec(
        select(DocumentChunk, Document)
        .join(Document, col(Document.id) == col(DocumentChunk.document_id))
        .where(col(DocumentChunk.id).in_(best))
    ).all()
    by_id = {c.id: (c, d) for c, d in rows}
    for cid in best:
        chunk, doc = by_id[cid]
        out.passages.append(
            Passage(
                document=doc,
                chunk_id=cid,
                position=chunk.position,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                text=chunk.text,
                score=round(scores[cid], 6),
                keyword_rank=k_rank.get(cid),
                vector_rank=v_rank.get(cid),
                similarity=round(sims[cid], 4) if cid in sims else None,
            )
        )
    return out
