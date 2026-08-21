"""Per-article sentiment scores, one row per (article, model).

``news_articles.sentiment`` is a single ``VARCHAR(16)`` label. That was enough
for a coloured badge and nothing else: it cannot hold a continuous score or a
confidence, and — most limiting — it doesn't record *which model* produced the
judgement. Without that you can't re-score an archive, compare two models, or
upgrade a model without destroying the history you'd want to compare against.

This table carries the full result. ``news_articles.sentiment`` stays as a
denormalized "current best" cache so existing reads and the badge keep working
unchanged.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class NewsSentiment(SQLModel, table=True):
    __tablename__ = "news_sentiment"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # One score per model per article: re-running a model updates in place,
        # while a second model adds a row alongside rather than overwriting.
        UniqueConstraint("article_id", "model", name="uq_news_sentiment_article_model"),
    )

    id: int | None = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="news_articles.id", index=True)

    # e.g. "claude-haiku-4-5-20251001", "finbert-v2". Free-form so an external
    # scoring service can name its own model without a migration here.
    model: str = Field(max_length=128, index=True)

    label: str = Field(max_length=16)
    # Continuous signal in [-1, 1] — this is what the rolling aggregates use.
    score: Decimal = Field(sa_column=Column(Numeric(6, 4), nullable=False))
    # Not every model reports one; NULL means "unknown", not "zero".
    confidence: Decimal | None = Field(default=None, sa_column=Column(Numeric(5, 4), nullable=True))

    scored_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
