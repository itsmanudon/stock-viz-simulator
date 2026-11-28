"""Company documents: filings, concall transcripts, announcements (A7.10, M5.5).

The owner's 27 Nov 2026 decision: filings and concalls live in a StockViz
``documents`` module, not in Aegis. One row per document, keyed by
``instrument_id`` (no ticker column, like theses and drawings); its text in
``document_texts``. ``available_at`` is when the document became public
(naive UTC): every read is point-in-time on it. ``sha256`` of the source bytes
is unique, so the same file or filing loads once.

``document_chunks`` (A8.4, M11.1): overlapping passages of the text, the unit
of hybrid search. Keyword ranking is PostgreSQL full text over ``text`` (a GIN
expression index in the migration); ``embedding`` is the passage's vector from
``embed_model`` (null until ``docs-index --embed`` runs), stored as ``real[]``
and compared in Python, because pgvector is not on every host yet (JSON on
SQLite, the test database).

``context`` (A8.8): a model-written line situating the passage (company,
filing, period, section), searched and embedded together with ``text``; the
full-text index is on ``coalesce(context, '') || ' ' || text``.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, REAL
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow

DOCUMENT_KINDS = ("filing", "concall_transcript", "announcement", "annual_report", "other")
DOCUMENT_SOURCES = ("file", "edgar")
KIND_SQL = ", ".join(f"'{k}'" for k in DOCUMENT_KINDS)
SOURCE_SQL = ", ".join(f"'{s}'" for s in DOCUMENT_SOURCES)


class Document(SQLModel, table=True):
    __tablename__ = "documents"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(f"kind IN ({KIND_SQL})", name="ck_documents_kind"),
        CheckConstraint(f"source IN ({SOURCE_SQL})", name="ck_documents_source"),
        Index("ix_documents_instrument_available", "instrument_id", "available_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(foreign_key="instruments.id")
    kind: str = Field(max_length=24)
    source: str = Field(max_length=16)
    form_type: str | None = Field(default=None, max_length=24)
    title: str = Field(max_length=300)
    event_date: date_type | None = None
    available_at: datetime
    available_assumed: bool = False
    url: str | None = Field(default=None, max_length=500)
    accession: str | None = Field(default=None, max_length=32, index=True)
    sha256: str = Field(max_length=64, unique=True)
    content_type: str = Field(max_length=16)
    size_bytes: int
    text_chars: int
    created_at: datetime = Field(default_factory=utcnow)


class DocumentText(SQLModel, table=True):
    __tablename__ = "document_texts"  # pyright: ignore[reportAssignmentType]

    document_id: int = Field(foreign_key="documents.id", primary_key=True, ondelete="CASCADE")
    text: str = Field(sa_column=Column(Text, nullable=False))


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_document_chunks_document_position", "document_id", "position"),)

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(
        sa_column=Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    )
    position: int
    start_char: int
    end_char: int
    text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(ARRAY(REAL()).with_variant(JSON(), "sqlite"), nullable=True),
    )
    embed_model: str | None = Field(default=None, max_length=64)
    # A8.8 (28 Nov 2026): one line situating the passage in its filing (company,
    # filing, period, section, what it covers), written by a model; searched and
    # embedded with the text, never shown as the filing's own words.
    context: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    context_model: str | None = Field(default=None, max_length=64)
