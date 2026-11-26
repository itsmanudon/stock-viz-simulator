"""The automatic trial ledger and holdout unlocks (A4.3, M7.4).

``backtest_trials``: one row per distinct backtest a caller ran (strategy
hash x data fingerprint x caller), saved or not: the public endpoints,
saved runs, and each member of a sweep or walk-forward. A repeat of the same
run bumps ``runs`` and ``last_run_at``. ``family_key`` groups variants of one
idea (``services/backtest/trials.py``), and the Deflated Sharpe Ratio reads
the number of distinct variants and the variance of their Sharpes from it.
Anonymous runs have ``user_id`` NULL: one shared pool, nothing that names a
visitor (no address, no cookie). Pruned by ``stockviz.cli prune-trials``.

``holdout_unlocks``: a user's one-time unlock of a strategy family's locked
holdout, with its time; after it every run of the family shows the holdout
as "seen".
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Column, ForeignKey, Index, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class BacktestTrial(SQLModel, table=True):
    __tablename__ = "backtest_trials"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_backtest_trials_family_user", "family_key", "user_id"),
        Index("ix_backtest_trials_hash", "strategy_hash", "data_fingerprint"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    )
    mode: str = Field(max_length=16)
    """``template`` or ``strategy``."""
    source: str = Field(max_length=16)
    """``run`` (public endpoint), ``saved``, ``sweep`` or ``walk_forward``."""
    family_key: str = Field(max_length=64)
    family_label: str = Field(max_length=120)
    strategy_hash: str = Field(max_length=64)
    data_fingerprint: str = Field(max_length=64)
    label: str = Field(max_length=200)
    observations: int
    sharpe: float
    """Per-day Sharpe of the net excess returns (annualised / sqrt(252))."""
    total_return: float
    runs: int = 1
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    last_run_at: datetime = Field(default_factory=utcnow, nullable=False)


class HoldoutUnlock(SQLModel, table=True):
    __tablename__ = "holdout_unlocks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "family_key", name="uq_holdout_unlocks_family"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    family_key: str = Field(max_length=64)
    family_label: str = Field(max_length=120)
    holdout_from: date
    holdout_to: date
    unlocked_at: datetime = Field(default_factory=utcnow, nullable=False)
