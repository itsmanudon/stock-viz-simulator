"""A8.8 contextual passages (M11.1).

Revision ID: f2b4d6e8a0c1
Revises: e9c5f7a1b3d4
Create Date: 2026-11-28 12:00:00.000000

- ``document_chunks.context`` / ``context_model``: a model-written line that
  situates each passage in its filing (company, filing, period, section).
- The full-text GIN index moves from ``to_tsvector('english', text)`` to
  ``to_tsvector('english', coalesce(context, '') || ' ' || text)``, the
  expression keyword ranking uses.

Additive. Contexts cost paid model calls to rebuild, so the downgrade refuses
while any passage has one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b4d6e8a0c1"
down_revision: str | None = "e9c5f7a1b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_TEXT = "coalesce(context, '') || ' ' || text"


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("context", sa.Text(), nullable=True))
    op.add_column(
        "document_chunks", sa.Column("context_model", sa.String(length=64), nullable=True)
    )
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks "
        f"USING gin (to_tsvector('english', {SEARCH_TEXT}))"
    )


def downgrade() -> None:
    stored = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM document_chunks WHERE context IS NOT NULL"))
        .scalar_one()
    )
    if stored:
        raise RuntimeError(
            f"{stored} passage(s) have a context; export them (docs-context --export) first"
        )
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_tsv")
    op.execute(
        "CREATE INDEX ix_document_chunks_tsv ON document_chunks "
        "USING gin (to_tsvector('english', text))"
    )
    op.drop_column("document_chunks", "context_model")
    op.drop_column("document_chunks", "context")
