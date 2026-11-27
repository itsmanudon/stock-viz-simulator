"""A7.10 company documents: filings, concall transcripts, announcements.

Revision ID: a7d1c3e5f9b2
Revises: f1a9c7e3b5d2
Create Date: 2026-11-27 10:00:00.000000

- ``documents``: one per document, keyed by ``instrument_id``; ``available_at``
  (naive UTC) is when it became public and every read is point-in-time on it;
  ``sha256`` of the source bytes is unique; kind and source checks.
- ``document_texts``: its text (cascade from the document).

Additive. The downgrade refuses while any document is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d1c3e5f9b2"
down_revision: str | None = "f1a9c7e3b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = "kind IN ('filing', 'concall_transcript', 'announcement', 'annual_report', 'other')"
SOURCES = "source IN ('file', 'edgar')"


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("form_type", sa.String(length=24), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("available_assumed", sa.Boolean(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("accession", sa.String(length=32), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(KINDS, name="ck_documents_kind"),
        sa.CheckConstraint(SOURCES, name="ck_documents_source"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(
        "ix_documents_instrument_available", "documents", ["instrument_id", "available_at"]
    )
    op.create_index("ix_documents_accession", "documents", ["accession"])
    op.create_table(
        "document_texts",
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    conn = op.get_bind()
    stored = conn.execute(sa.text("SELECT count(*) FROM documents")).scalar_one()
    if stored:
        raise RuntimeError(
            f"{stored} documents are stored; export or delete them before downgrading"
        )
    op.drop_table("document_texts")
    op.drop_index("ix_documents_accession", table_name="documents")
    op.drop_index("ix_documents_instrument_available", table_name="documents")
    op.drop_table("documents")
