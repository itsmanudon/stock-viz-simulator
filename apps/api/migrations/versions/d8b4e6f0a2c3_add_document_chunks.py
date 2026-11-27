"""A8.4 document chunks for hybrid search (M11.1).

Revision ID: d8b4e6f0a2c3
Revises: c8a3d5f7e9b1
Create Date: 2026-11-27 18:00:00.000000

- ``document_chunks``: overlapping passages of each document's text (cascade
  from the document), with an optional ``real[]`` embedding and its model.
- A GIN index on ``to_tsvector('english', text)`` for keyword ranking.

No pgvector: vectors are compared in Python until the extension is confirmed on
every host. Additive; chunks are rebuilt by ``docs-index``, so the downgrade
drops them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8b4e6f0a2c3"
down_revision: str | None = "c8a3d5f7e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(postgresql.REAL()), nullable=True),
        sa.Column("embed_model", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_document_chunks_document_position", "document_chunks", ["document_id", "position"]
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks "
        "USING gin (to_tsvector('english', text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.drop_index("ix_document_chunks_document_position", table_name="document_chunks")
    op.drop_table("document_chunks")
