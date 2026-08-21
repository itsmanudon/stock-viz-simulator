"""add news_sentiment

One row per (article, model): label, continuous score, optional confidence.
``news_articles.sentiment`` was a bare label column with no record of which
model produced it, so an archive could never be re-scored or two models
compared. That column stays as the denormalized "current best" cache the badge
reads.

Revision ID: 9c41c7572753
Revises: ebd81d50b469
Create Date: 2026-08-21 06:06:02.470697

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "9c41c7572753"
down_revision: str | None = "ebd81d50b469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_sentiment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("scored_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news_articles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "model", name="uq_news_sentiment_article_model"),
    )
    op.create_index(
        op.f("ix_news_sentiment_article_id"), "news_sentiment", ["article_id"], unique=False
    )
    op.create_index(op.f("ix_news_sentiment_model"), "news_sentiment", ["model"], unique=False)
    op.create_index(
        op.f("ix_news_sentiment_scored_at"), "news_sentiment", ["scored_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_news_sentiment_scored_at"), table_name="news_sentiment")
    op.drop_index(op.f("ix_news_sentiment_model"), table_name="news_sentiment")
    op.drop_index(op.f("ix_news_sentiment_article_id"), table_name="news_sentiment")
    op.drop_table("news_sentiment")
