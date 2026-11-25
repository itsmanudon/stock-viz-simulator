"""The spine (A2.2): setups, their immutable versions, and theses.

A **setup** is a named rule a user keeps (a screen, an alert, a strategy or a
checklist). Its rule lives in **setup versions**: rows that are never updated.
Editing a setup adds version n+1; saving a rule the setup already has returns
that version (unique ``(setup_id, rule_hash)``), so a version names exactly
one rule. Saved screens, alerts and experiment runs carry a nullable
``setup_version_id``, so later batches (A2.3 alerts, A5 journal) can trace a
result back to the exact rule.

System presets are setups with ``user_id`` null and ``is_preset`` true,
written by ``stockviz.cli seed`` (``services/setups/presets.py``). They are
read-only: a user forks one into a setup of their own.

A **thesis** (M5.6) is a written view on one instrument with an optional kill
rule in the Rule DSL. Nothing evaluates the kill rule yet (A2.3 / A5); it
must compile when it is saved.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

SETUP_KINDS = ("screen", "alert", "strategy", "checklist")
THESIS_STATUSES = ("open", "invalidated", "closed")
TIMEFRAMES = ("daily",)
"""A rule is judged on daily bars; ``weekly.`` / ``monthly.`` live inside it."""


class Setup(SQLModel, table=True):
    __tablename__ = "setups"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "kind IN ('screen', 'alert', 'strategy', 'checklist')", name="ck_setups_kind"
        ),
        CheckConstraint(
            "(is_preset AND user_id IS NULL) OR (NOT is_preset AND user_id IS NOT NULL)",
            name="ck_setups_preset_owner",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Null only for system presets.
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    name: str = Field(max_length=120)
    kind: str = Field(max_length=16)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    is_preset: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false())
    )
    # The version this setup was forked from (a preset's or the user's own).
    forked_from_version_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "setup_versions.id", use_alter=True, name="fk_setups_forked_from_version_id"
            ),
            nullable=True,
        ),
    )
    # Presets are found by this key on reseed; null for user setups.
    preset_key: str | None = Field(default=None, max_length=64, unique=True, nullable=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    archived_at: datetime | None = Field(default=None, nullable=True)


class SetupVersion(SQLModel, table=True):
    """One rule of a setup. Immutable: no code path updates a row."""

    __tablename__ = "setup_versions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("setup_id", "version", name="uq_setup_versions_setup_version"),
        UniqueConstraint("setup_id", "rule_hash", name="uq_setup_versions_setup_rule_hash"),
    )

    id: int | None = Field(default=None, primary_key=True)
    setup_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("setups.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    version: int
    rule_text: str = Field(sa_column=Column(Text, nullable=False))
    canonical_text: str = Field(sa_column=Column(Text, nullable=False))
    rule_hash: str = Field(max_length=64, index=True)
    timeframe: str = Field(default="daily", max_length=16)
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Thesis(SQLModel, table=True):
    __tablename__ = "theses"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("status IN ('open', 'invalidated', 'closed')", name="ck_theses_status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    instrument_id: int = Field(foreign_key="instruments.id", index=True)
    title: str = Field(max_length=160)
    body: str = Field(sa_column=Column(Text, nullable=False))
    kill_rule_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    kill_rule_hash: str | None = Field(default=None, max_length=64, nullable=True)
    status: str = Field(default="open", max_length=16)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = ["SETUP_KINDS", "THESIS_STATUSES", "TIMEFRAMES", "Setup", "SetupVersion", "Thesis"]
