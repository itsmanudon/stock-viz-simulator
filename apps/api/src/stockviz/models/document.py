"""Company documents: filings, concall transcripts, announcements (A7.10, M5.5).

The owner's 27 Nov 2026 decision: filings and concalls live in a StockViz
``documents`` module, not in Aegis. One row per document, keyed by
``instrument_id`` (no ticker column, like theses and drawings); its text in
``document_texts``. ``available_at`` is when the document became public
(naive UTC): every read is point-in-time on it. ``sha256`` of the source bytes
is unique, so the same file or filing loads once.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Text
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
