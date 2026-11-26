"""`/v1/chart-templates` (A6.8, M2.10): saved chart looks. Authed.

``GET ""`` lists yours; ``POST ""`` ``{name, chart_type, scale, indicators,
pane_heights}`` (201); ``PATCH /{id}`` (any of those); ``DELETE /{id}`` (204;
layouts that used it fall back to the default look). Indicator keys follow
the indicator catalog's grammar (``/v1/indicators/catalog``); the rules are
in ``services/chart_templates.py``. Another user's template is 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import ChartTemplate
from stockviz.schemas import ChartTemplateIn, ChartTemplateOut, ChartTemplatePatch
from stockviz.services import chart_templates as svc

router = APIRouter(prefix="/v1/chart-templates", tags=["charts"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(row: ChartTemplate) -> ChartTemplateOut:
    assert row.id is not None
    return ChartTemplateOut(
        id=row.id,
        name=row.name,
        chart_type=row.chart_type,  # type: ignore[arg-type]
        scale=row.scale,  # type: ignore[arg-type]
        indicators=list(row.indicators),
        pane_heights=dict(row.pane_heights),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[ChartTemplateOut])
def list_chart_templates(session: SessionDep, user_id: UserIdDep) -> list[ChartTemplateOut]:
    return [_out(row) for row in svc.templates_of(session, user_id)]


@router.post("", response_model=ChartTemplateOut, status_code=status.HTTP_201_CREATED)
def create_chart_template(
    body: ChartTemplateIn, session: SessionDep, user_id: UserIdDep
) -> ChartTemplateOut:
    return _out(
        svc.create_template(
            session,
            user_id,
            name=body.name,
            chart_type=body.chart_type,
            scale=body.scale,
            indicators=body.indicators,
            pane_heights=body.pane_heights,
        )
    )


@router.patch("/{template_id}", response_model=ChartTemplateOut)
def update_chart_template(
    template_id: int, body: ChartTemplatePatch, session: SessionDep, user_id: UserIdDep
) -> ChartTemplateOut:
    return _out(
        svc.update_template(
            session, user_id, template_id, fields=body.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chart_template(template_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    svc.delete_template(session, user_id, template_id)
