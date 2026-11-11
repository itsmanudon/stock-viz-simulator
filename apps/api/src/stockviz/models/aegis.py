"""Read-only copies of Aegis News data (Phase 2).

StockViz copies what the Aegis feed returns into these tables once a night
(``stockviz.cli aegis-sync``). Pages read these tables and never call Aegis
live, so an Aegis outage cannot break a StockViz page.

Contract: ``docs/contracts/aegis-read-v1.md`` in the workspace and
``aegis-news/docs/feed.md``. Rules that shaped the tables:

- **No article text.** The feed sends none and nothing here stores any.
- **Point in time.** Order and filter by ``available_at``, never by
  ``published_at``, which is empty for every GDELT document (audit AG-12).
  Each analysis has its own ``available_at``.
- **Model identity on every score.** Analyses keep provider, model name and
  model version, and the raw label as Aegis sent it, including ``mixed``
  (audit AG-4).
- **A bundle replaces what is held.** Each feed bundle is the document as of
  its latest signed run, so the sync replaces a document's analyses, entities
  and events rather than merging them.
- **Mappings join locally.** Documents keep every entity they resolved to.
  The mapping list is read whole on each sync, so a mapping added later
  applies to documents already held (audit AG-2).

Timestamps are stored as naive UTC, like the rest of the schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


def _document_fk() -> Column:
    return Column(
        String(64),
        ForeignKey("aegis_documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class AegisDocument(SQLModel, table=True):
    """One signed Aegis document: headline, link and clocks. Never the text."""

    __tablename__ = "aegis_documents"  # pyright: ignore[reportAssignmentType]

    document_id: str = Field(max_length=64, primary_key=True)
    source_id: str = Field(max_length=64)
    source_name: str = Field(max_length=512)
    source_url: str | None = Field(default=None, max_length=2048)
    title: str = Field(max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=35)
    # The publisher's claim. Display only: empty for every GDELT document.
    published_at: datetime | None = Field(default=None)
    first_seen_at: datetime
    # When Aegis first made the document available. Never changes. The key
    # every point-in-time read orders and filters by.
    available_at: datetime = Field(index=True)
    # When the latest signed run completed; moves on re-analysis.
    last_signed_at: datetime
    revision: int = Field(default=1)
    # The newest signed manifest covering the bundle (offline verification).
    manifest_hash: str | None = Field(default=None, max_length=64)
    manifest_key_id: str | None = Field(default=None, max_length=128)
    synced_at: datetime = Field(default_factory=utcnow)


class AegisAnalysis(SQLModel, table=True):
    """One analysis from the document's latest signed run.

    The feed returns ``topic``, ``sentiment`` and ``entity_resolution``.
    ``label`` and ``score`` repeat the first output for queries; ``outputs``
    keeps everything Aegis sent.
    """

    __tablename__ = "aegis_analyses"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_aegis_analyses_type_available", "analysis_type", "available_at"),)

    analysis_id: str = Field(max_length=64, primary_key=True)
    document_id: str = Field(sa_column=_document_fk())
    analysis_type: str = Field(max_length=32)
    provider: str = Field(max_length=128)
    model_name: str = Field(max_length=256)
    model_version: str = Field(max_length=128)
    configuration_hash: str = Field(max_length=64)
    available_at: datetime
    # Raw label as sent: positive, neutral, negative or mixed for sentiment.
    label: str | None = Field(default=None, max_length=64)
    score: float | None = Field(default=None)
    confidence: float | None = Field(default=None)
    outputs: list[dict[str, Any]] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )


class AegisDocumentEntity(SQLModel, table=True):
    """An entity the document resolved to, mapped to a listing or not."""

    __tablename__ = "aegis_document_entities"  # pyright: ignore[reportAssignmentType]

    document_id: str = Field(
        sa_column=Column(
            String(64),
            ForeignKey("aegis_documents.document_id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    entity_id: str = Field(max_length=64, primary_key=True, index=True)
    canonical_name: str = Field(max_length=512)
    kind: str = Field(max_length=32)
    resolution_analysis_id: str = Field(max_length=64)
    confidence: float


class AegisEvent(SQLModel, table=True):
    """A typed event from the document's latest signed run. No summary text."""

    __tablename__ = "aegis_events"  # pyright: ignore[reportAssignmentType]

    event_id: str = Field(max_length=64, primary_key=True)
    revision: int = Field(primary_key=True)
    document_id: str = Field(sa_column=_document_fk())
    event_type: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None)
    occurred_at: datetime | None = Field(default=None)
    available_at: datetime
    evidence_kind: str = Field(max_length=32)
    analysis_id: str | None = Field(default=None, max_length=64)


class AegisMapping(SQLModel, table=True):
    """One Aegis asset mapping. The whole list is replaced on every sync.

    StockViz joins on ``scheme == "provider_id"`` and
    ``identifier == "stockviz:<ticker>"`` (Aegis seed ``stockviz.json``).
    """

    __tablename__ = "aegis_mappings"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_aegis_mappings_scheme_identifier", "scheme", "identifier"),)

    mapping_id: str = Field(max_length=64, primary_key=True)
    entity_id: str = Field(max_length=64, index=True)
    scheme: str = Field(max_length=32)
    identifier: str = Field(max_length=512)
    venue: str | None = Field(default=None, max_length=512)
    created_at: datetime


class AegisSyncState(SQLModel, table=True):
    """Where the next sync resumes. One row, written with each page."""

    __tablename__ = "aegis_sync_state"  # pyright: ignore[reportAssignmentType]

    id: int = Field(default=1, primary_key=True)
    cursor: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(default_factory=utcnow)


class AegisSyncRun(SQLModel, table=True):
    """One run of the sync: the record a failed night leaves behind."""

    __tablename__ = "aegis_sync_runs"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = Field(default=None)
    # running, succeeded or failed
    status: str = Field(default="running", max_length=16)
    pages: int = Field(default=0)
    documents_upserted: int = Field(default=0)
    documents_withdrawn: int = Field(default=0)
    mappings: int = Field(default=0)
    # Aegis's as_of for the last page read.
    aegis_as_of: datetime | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
