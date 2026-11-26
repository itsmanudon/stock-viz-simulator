"""Chart templates (A6.8, M2.10): a saved chart look, per user.

- **Name:** 1 to 64 characters, spaces collapsed, unique per user ignoring
  case (409).
- **Cap:** at most ``MAX_TEMPLATES_PER_USER`` a user (409).
- **Indicators:** each key must parse in the indicator registry's grammar
  (``services/indicators/engine.parse``: a known study, at most its
  parameter count, each value in its bounds), else 422. Kept lower-cased, in
  order, each once, at most ``MAX_TEMPLATE_INDICATORS``.
- **Pane heights:** pane kinds (``price``, ``volume``, ``rsi``, a study key)
  to whole pixels from ``MIN_PANE_HEIGHT`` to ``MAX_PANE_HEIGHT``, at most
  ``MAX_PANE_KINDS`` of them (422).
- **Delete:** clears the template from every one of the user's layouts that
  used it (the panes fall back to the default look).

Another user's template is 404.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models.chart_layout import (
    MAX_PANE_HEIGHT,
    MAX_PANE_KINDS,
    MAX_TEMPLATE_INDICATORS,
    MAX_TEMPLATES_PER_USER,
    MIN_PANE_HEIGHT,
    ChartLayout,
    ChartTemplate,
)
from stockviz.services.indicators import engine

NAME_MAX = 64
_PANE_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name or len(name) > NAME_MAX:
        raise HTTPException(422, f"A name is 1 to {NAME_MAX} characters")
    return name


def clean_indicators(raw: Sequence[str]) -> list[str]:
    out: list[str] = []
    for token in raw:
        try:
            key = engine.parse(token).name
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if key not in out:
            out.append(key)
    if len(out) > MAX_TEMPLATE_INDICATORS:
        raise HTTPException(422, f"A template holds at most {MAX_TEMPLATE_INDICATORS} indicators")
    return out


def clean_pane_heights(raw: Mapping[str, int]) -> dict[str, int]:
    if len(raw) > MAX_PANE_KINDS:
        raise HTTPException(422, f"At most {MAX_PANE_KINDS} pane heights")
    out: dict[str, int] = {}
    for kind, value in raw.items():
        if not _PANE_KIND.match(kind):
            raise HTTPException(422, f"Unknown pane kind: {kind!r}")
        if not MIN_PANE_HEIGHT <= value <= MAX_PANE_HEIGHT:
            raise HTTPException(
                422, f"A pane height is {MIN_PANE_HEIGHT} to {MAX_PANE_HEIGHT} pixels"
            )
        out[kind] = int(value)
    return out


def templates_of(session: Session, user_id: int) -> list[ChartTemplate]:
    return list(
        session.exec(
            select(ChartTemplate)
            .where(col(ChartTemplate.user_id) == user_id)
            .order_by(col(ChartTemplate.id))
        )
    )


def template_ids_of(session: Session, user_id: int) -> set[int]:
    return {
        row
        for row in session.exec(
            select(ChartTemplate.id).where(col(ChartTemplate.user_id) == user_id)
        )
        if row is not None
    }


def get_template(session: Session, user_id: int, template_id: int) -> ChartTemplate:
    row = session.get(ChartTemplate, template_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chart template not found")
    return row


def _name_taken(session: Session, user_id: int, name: str, *, except_id: int | None) -> bool:
    return any(
        t.id != except_id and t.name.casefold() == name.casefold()
        for t in templates_of(session, user_id)
    )


def create_template(
    session: Session,
    user_id: int,
    *,
    name: str,
    chart_type: str,
    scale: str,
    indicators: Sequence[str],
    pane_heights: Mapping[str, int],
) -> ChartTemplate:
    name = clean_name(name)
    cleaned = clean_indicators(indicators)
    heights = clean_pane_heights(pane_heights)
    if len(templates_of(session, user_id)) >= MAX_TEMPLATES_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"At most {MAX_TEMPLATES_PER_USER} chart templates; delete one first",
        )
    if _name_taken(session, user_id, name, except_id=None):
        raise HTTPException(status.HTTP_409_CONFLICT, f"You already have a template named {name!r}")
    row = ChartTemplate(
        user_id=user_id,
        name=name,
        chart_type=chart_type,
        scale=scale,
        indicators=cleaned,
        pane_heights=heights,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_template(
    session: Session, user_id: int, template_id: int, *, fields: dict[str, Any]
) -> ChartTemplate:
    row = get_template(session, user_id, template_id)
    if fields.get("name") is not None:
        name = clean_name(fields["name"])
        if _name_taken(session, user_id, name, except_id=row.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"You already have a template named {name!r}"
            )
        row.name = name
    if fields.get("chart_type") is not None:
        row.chart_type = fields["chart_type"]
    if fields.get("scale") is not None:
        row.scale = fields["scale"]
    if fields.get("indicators") is not None:
        row.indicators = clean_indicators(fields["indicators"])
    if fields.get("pane_heights") is not None:
        row.pane_heights = clean_pane_heights(fields["pane_heights"])
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_template(session: Session, user_id: int, template_id: int) -> None:
    row = get_template(session, user_id, template_id)
    for layout in session.exec(select(ChartLayout).where(col(ChartLayout.user_id) == user_id)):
        if any(p.get("template_id") == row.id for p in layout.panes):
            layout.panes = [
                {**p, "template_id": None} if p.get("template_id") == row.id else p
                for p in layout.panes
            ]
            layout.updated_at = utcnow()
            session.add(layout)
    session.flush()
    session.delete(row)
    session.commit()


__all__ = [
    "clean_indicators",
    "clean_name",
    "clean_pane_heights",
    "create_template",
    "delete_template",
    "get_template",
    "template_ids_of",
    "templates_of",
    "update_template",
]
