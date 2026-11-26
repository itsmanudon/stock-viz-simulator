"""`/v1/chart-layouts` (A6.8, M2.10): saved chart workspaces. Authed.

``GET ""`` lists yours; ``GET /{id}``; ``POST ""`` ``{name, grid, panes}``
(201); ``PATCH /{id}`` ``{name?, grid?, panes?}`` (a grid change sends its
panes); ``DELETE /{id}`` (204). A pane is ``{symbol, interval, template_id,
link}``; the rules (known symbols, own templates, one symbol per link colour)
are in ``services/chart_layouts.py``. Another user's layout is 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import ChartLayoutIn, ChartLayoutOut, ChartLayoutPatch
from stockviz.services import chart_layouts as svc
from stockviz.services.chart_templates import template_ids_of

router = APIRouter(prefix="/v1/chart-layouts", tags=["charts"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[ChartLayoutOut])
def list_chart_layouts(session: SessionDep, user_id: UserIdDep) -> list[ChartLayoutOut]:
    own = template_ids_of(session, user_id)
    return [svc.layout_out(row, own) for row in svc.layouts_of(session, user_id)]


@router.get("/{layout_id}", response_model=ChartLayoutOut)
def get_chart_layout(layout_id: int, session: SessionDep, user_id: UserIdDep) -> ChartLayoutOut:
    row = svc.get_layout(session, user_id, layout_id)
    return svc.layout_out(row, template_ids_of(session, user_id))


@router.post("", response_model=ChartLayoutOut, status_code=status.HTTP_201_CREATED)
def create_chart_layout(
    body: ChartLayoutIn, session: SessionDep, user_id: UserIdDep
) -> ChartLayoutOut:
    row = svc.create_layout(session, user_id, name=body.name, grid=body.grid, panes=body.panes)
    return svc.layout_out(row, template_ids_of(session, user_id))


@router.patch("/{layout_id}", response_model=ChartLayoutOut)
def update_chart_layout(
    layout_id: int, body: ChartLayoutPatch, session: SessionDep, user_id: UserIdDep
) -> ChartLayoutOut:
    row = svc.update_layout(
        session, user_id, layout_id, name=body.name, grid=body.grid, panes=body.panes
    )
    return svc.layout_out(row, template_ids_of(session, user_id))


@router.delete("/{layout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chart_layout(layout_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    svc.delete_layout(session, user_id, layout_id)
