"""Session-only chart drawings (A4.6, M9.1).

A drawing made on the live chart could sit on a later date and show the
future, so a replay session shows only the drawings made inside it, kept in
``replay_drawings`` (never ``drawings``): the live chart, ``drawing()``
rules and other sessions cannot read them, and the session never reads live
ones. The rules per kind are A3.2's (``services/drawings.validate_points``),
with anchors between the session's first bar and its clock (nothing anchored
after ``current_at``). An anchored VWAP is not offered: its line is computed
from every stored bar, so replay refuses the kind (422).
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import ReplayDrawing, ReplaySession
from stockviz.models.drawing import MAX_DRAWINGS_PER_INSTRUMENT
from stockviz.schemas import DrawingOut, DrawingPoint, DrawingStyle
from stockviz.services.bars.resample import bar_date
from stockviz.services.drawings import points_json, position_metrics, validate_points
from stockviz.services.markets.calendar import venue_for_ticker

MAX_REPLAY_DRAWINGS = MAX_DRAWINGS_PER_INSTRUMENT
REPLAY_REFUSED_KINDS = frozenset({"avwap"})


def anchor_range(replay: ReplaySession) -> tuple[date, date]:
    """The venue dates a session drawing may be anchored between."""
    venue = venue_for_ticker(replay.ticker)
    return bar_date(replay.start_at, venue), bar_date(replay.current_at, venue)


def check_kind(kind: str) -> None:
    if kind in REPLAY_REFUSED_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "An anchored VWAP is not available in replay (its line reads every stored bar)",
        )


def validate(replay: ReplaySession, kind: str, points: list[DrawingPoint], label: str | None):
    check_kind(kind)
    first, last = anchor_range(replay)
    validate_points(kind, points, label, first, last)


def list_drawings(db: Session, replay: ReplaySession) -> list[ReplayDrawing]:
    return list(
        db.exec(
            select(ReplayDrawing)
            .where(ReplayDrawing.session_id == replay.id)
            .order_by(col(ReplayDrawing.created_at), col(ReplayDrawing.id))
        ).all()
    )


def count(db: Session, replay: ReplaySession) -> int:
    return db.exec(
        select(func.count())
        .select_from(ReplayDrawing)
        .where(col(ReplayDrawing.session_id) == replay.id)
    ).one()


def owned(db: Session, replay: ReplaySession, drawing_id: int) -> ReplayDrawing:
    row = db.get(ReplayDrawing, drawing_id)
    if row is None or row.session_id != replay.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Drawing {drawing_id} not found")
    return row


def points_of(row: ReplayDrawing) -> list[DrawingPoint]:
    return [DrawingPoint.model_validate(p) for p in row.points]


def drawing_out(row: ReplayDrawing, ticker: str) -> DrawingOut:
    assert row.id is not None
    points = points_of(row)
    return DrawingOut(
        id=row.id,
        ticker=ticker,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        points=points,
        style=DrawingStyle.model_validate(row.style),
        label=row.label,
        locked=row.locked,
        position=position_metrics(row.kind, points),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def touch(row: ReplayDrawing) -> None:
    row.updated_at = utcnow()


__all__ = [
    "MAX_REPLAY_DRAWINGS",
    "anchor_range",
    "check_kind",
    "count",
    "drawing_out",
    "list_drawings",
    "owned",
    "points_json",
    "points_of",
    "touch",
    "validate",
]
