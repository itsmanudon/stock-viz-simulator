"""Chart layouts (A6.8, M2.10): a saved chart workspace, per user.

- **Name:** as templates (1 to 64 characters, unique per user ignoring case,
  409).
- **Cap:** at most ``MAX_LAYOUTS_PER_USER`` a user (409).
- **Grid and panes:** exactly the grid's pane count (``1``: 1, ``2v`` and
  ``2h``: 2, ``4``: 4), else 422. Each pane's symbol must be a known symbol
  (upper-cased), its template one of the user's own (else 422), its interval
  one the bars route serves (the schema checks it).
- **Linked groups:** panes of one colour share one symbol (422 otherwise),
  since a pane in a colour follows the last symbol chosen in it. No colour
  is unlinked.

A read drops a template id the user no longer has (a deleted template).
Another user's layout is 404.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import Symbol
from stockviz.models.chart_layout import GRID_PANES, MAX_LAYOUTS_PER_USER, ChartLayout
from stockviz.schemas import ChartLayoutOut, ChartPaneIn, ChartPaneOut
from stockviz.services.chart_templates import clean_name, template_ids_of


def layouts_of(session: Session, user_id: int) -> list[ChartLayout]:
    return list(
        session.exec(
            select(ChartLayout)
            .where(col(ChartLayout.user_id) == user_id)
            .order_by(col(ChartLayout.id))
        )
    )


def get_layout(session: Session, user_id: int, layout_id: int) -> ChartLayout:
    row = session.get(ChartLayout, layout_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chart layout not found")
    return row


def clean_panes(
    session: Session, user_id: int, grid: str, panes: Sequence[ChartPaneIn]
) -> list[dict[str, Any]]:
    want = GRID_PANES[grid]
    if len(panes) != want:
        raise HTTPException(
            422, f"A {grid} grid has {want} pane{'s' if want > 1 else ''}; got {len(panes)}"
        )
    own = template_ids_of(session, user_id)
    by_colour: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for pane in panes:
        symbol = pane.symbol.strip().upper()
        if session.get(Symbol, symbol) is None:
            raise HTTPException(422, f"Unknown symbol: {symbol!r}")
        if pane.template_id is not None and pane.template_id not in own:
            raise HTTPException(422, f"Unknown chart template: {pane.template_id}")
        if pane.link is not None:
            first = by_colour.setdefault(pane.link, symbol)
            if first != symbol:
                raise HTTPException(
                    422,
                    f"Panes linked in {pane.link} share one symbol ({first}, not {symbol})",
                )
        out.append(
            {
                "symbol": symbol,
                "interval": pane.interval,
                "template_id": pane.template_id,
                "link": pane.link,
            }
        )
    return out


def _name_taken(session: Session, user_id: int, name: str, *, except_id: int | None) -> bool:
    return any(
        row.id != except_id and row.name.casefold() == name.casefold()
        for row in layouts_of(session, user_id)
    )


def create_layout(
    session: Session, user_id: int, *, name: str, grid: str, panes: Sequence[ChartPaneIn]
) -> ChartLayout:
    name = clean_name(name)
    cleaned = clean_panes(session, user_id, grid, panes)
    if len(layouts_of(session, user_id)) >= MAX_LAYOUTS_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"At most {MAX_LAYOUTS_PER_USER} chart layouts; delete one first",
        )
    if _name_taken(session, user_id, name, except_id=None):
        raise HTTPException(status.HTTP_409_CONFLICT, f"You already have a layout named {name!r}")
    row = ChartLayout(user_id=user_id, name=name, grid=grid, panes=cleaned)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_layout(
    session: Session,
    user_id: int,
    layout_id: int,
    *,
    name: str | None = None,
    grid: str | None = None,
    panes: Sequence[ChartPaneIn] | None = None,
) -> ChartLayout:
    row = get_layout(session, user_id, layout_id)
    if name is not None:
        cleaned_name = clean_name(name)
        if _name_taken(session, user_id, cleaned_name, except_id=row.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"You already have a layout named {cleaned_name!r}"
            )
        row.name = cleaned_name
    if grid is not None or panes is not None:
        if panes is None:
            raise HTTPException(422, "A new grid needs its panes")
        new_grid = grid or row.grid
        row.panes = clean_panes(session, user_id, new_grid, panes)
        row.grid = new_grid
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_layout(session: Session, user_id: int, layout_id: int) -> None:
    row = get_layout(session, user_id, layout_id)
    session.delete(row)
    session.commit()


def layout_out(row: ChartLayout, own_templates: set[int]) -> ChartLayoutOut:
    assert row.id is not None
    panes = [
        ChartPaneOut(
            symbol=p["symbol"],
            interval=p["interval"],
            template_id=p.get("template_id") if p.get("template_id") in own_templates else None,
            link=p.get("link"),
        )
        for p in row.panes
    ]
    return ChartLayoutOut(
        id=row.id,
        name=row.name,
        grid=row.grid,  # type: ignore[arg-type]
        panes=panes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "clean_panes",
    "create_layout",
    "delete_layout",
    "get_layout",
    "layout_out",
    "layouts_of",
    "update_layout",
]
