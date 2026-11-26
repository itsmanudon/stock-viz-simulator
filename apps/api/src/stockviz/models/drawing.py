"""Chart drawings (A3.2, M2.4): a user's lines, zones and position tools on
one instrument's chart.

An anchor is a bar time and a price, never a pixel: ``points`` is a list of
``{"ts": "YYYY-MM-DD" | null, "price": "123.45"}``, where ``ts`` is the
venue date of a daily bar's session. The web maps a daily anchor onto the
weekly or monthly bar whose period contains it, so a drawing lands on the
same dates and prices on every interval. Keyed by ``instrument_id`` (no
ticker column, so no identity trigger), like theses. The rules per kind live
in ``services/drawings.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")

DRAWING_KINDS = (
    "trendline",
    "ray",
    "hline",
    "rectangle",
    "channel",
    "fib_retracement",
    "fib_extension",
    "ruler",
    "text",
    "position_long",
    "position_short",
    "avwap",
    "volume_profile",
)

DRAWING_COLOURS = ("aqua", "blue", "violet", "pink", "amber", "lime", "slate", "foreground")
"""Colour token names: the list palette (``--list-<name>`` in the web) and
the foreground. The web resolves each to the theme's colour."""

LABEL_MAX = 80
MAX_DRAWINGS_PER_INSTRUMENT = 200


class Drawing(SQLModel, table=True):
    __tablename__ = "drawings"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{k}'" for k in DRAWING_KINDS) + ")",
            name="ck_drawings_kind",
        ),
        Index("ix_drawings_user_instrument", "user_id", "instrument_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    instrument_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    kind: str = Field(max_length=24)
    # [{ts: "YYYY-MM-DD" | null, price: "<decimal>" | null}], in the kind's order.
    # An avwap (A3.3) is one point {ts: anchor date, price: null}; a
    # volume_profile (A6.7) two, {ts: first or last session, price: null}.
    points: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(_JSON, nullable=False)
    )
    # {colour, width, dash, fill_opacity}
    style: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_JSON, nullable=False))
    label: str | None = Field(default=None, max_length=LABEL_MAX, nullable=True)
    locked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = [
    "DRAWING_COLOURS",
    "DRAWING_KINDS",
    "LABEL_MAX",
    "MAX_DRAWINGS_PER_INSTRUMENT",
    "Drawing",
]
