"""Per-user alert rules and their history (Phase 7.1).

A rule has a ``kind``: ``price`` (close above/below ``target_price``, or a
session move of ``params.pct``), ``technical`` (a registry indicator against
a number or another series), ``news`` and ``portfolio`` (Phase 7.2). Rules
are judged once per completed session and fire on a **crossing** (audit
RS-8): the condition was false at the last evaluation and is true now. Each
firing writes an ``AlertEvent`` whose ``dedupe_key`` is unique, so a rerun of
the night writes nothing twice. ``triggered_at`` is the last firing; the UI
shows triggered-but-undismissed rules on the bell.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import instrument_id_column


class AlertDirection(enum.StrEnum):
    ABOVE = "above"
    BELOW = "below"


class AlertKind(enum.StrEnum):
    PRICE = "price"
    TECHNICAL = "technical"
    NEWS = "news"
    PORTFOLIO = "portfolio"


class AlertRepeat(enum.StrEnum):
    ONCE = "once"
    EVERY_CROSS = "every_cross"


_JSON = JSON().with_variant(JSONB(), "postgresql")


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "kind = 'portfolio' OR ticker IS NOT NULL", name="ck_alerts_ticker_unless_portfolio"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    # Null only for portfolio rules, which watch the whole account.
    ticker: str | None = Field(
        default=None, foreign_key="symbols.ticker", index=True, max_length=16, nullable=True
    )
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column())
    kind: AlertKind = Field(
        default=AlertKind.PRICE,
        sa_column=Column(String(16), nullable=False, server_default="price"),
    )
    # Price-level rules keep their level here (split rebasing scales it).
    direction: AlertDirection | None = Field(default=None, max_length=8, nullable=True)
    target_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    # Per-kind settings, validated by ``services/alerts/rules.py``.
    params: dict | None = Field(default=None, sa_column=Column(_JSON, nullable=True))
    repeat: AlertRepeat = Field(
        default=AlertRepeat.ONCE,
        sa_column=Column(String(16), nullable=False, server_default="once"),
    )
    cooldown_sessions: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )
    paused: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false())
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    # When the rule last started watching (creation or re-arm). Its starting
    # state is judged on the newest close known at this time (RS-8).
    armed_at: datetime | None = Field(default=None, nullable=True)
    # Evaluation state: the condition at the last judged bar, and that bar.
    last_state: bool | None = Field(default=None, nullable=True)
    last_bar_date: date | None = Field(default=None, nullable=True)
    last_fired_bar_date: date | None = Field(default=None, nullable=True)
    # News rules: documents available after this were not yet looked at.
    last_seen_at: datetime | None = Field(default=None, nullable=True)
    triggered_at: datetime | None = Field(default=None, nullable=True)
    dismissed_at: datetime | None = Field(default=None, nullable=True)


class AlertEvent(SQLModel, table=True):
    """One firing of a rule: what was seen, against what, on which bar."""

    __tablename__ = "alert_events"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    alert_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    user_id: int = Field(foreign_key="users.id", index=True)
    kind: str = Field(max_length=16)
    ticker: str | None = Field(default=None, max_length=16)
    session_date: date
    bar_date: date | None = Field(default=None)
    observed: Decimal | None = Field(default=None, sa_column=Column(Numeric(24, 8), nullable=True))
    threshold: Decimal | None = Field(default=None, sa_column=Column(Numeric(24, 8), nullable=True))
    message: str = Field(max_length=500)
    # "bar", "document:<id>" or "portfolio".
    source: str = Field(max_length=80)
    # "<alert>:<bar date>" or "<alert>:doc:<id>": a rerun writes nothing twice.
    dedupe_key: str = Field(max_length=120, unique=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
