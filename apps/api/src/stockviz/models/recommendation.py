"""Algo-generated recommendations.

Populated by ``services/recommend/`` in Phase 5. We keep one row per (ticker,
computed_at) so we can backtest the recommender by looking at history.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class Recommendation(SQLModel, table=True):
    __tablename__ = "recommendations"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", index=True, max_length=16)
    score: Decimal = Field(sa_column=Column(Numeric(8, 4), nullable=False))
    rationale: str | None = None
    computed_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
