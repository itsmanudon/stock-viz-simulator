"""`/v1/column-sets` (A2.5, M4.6): saved watchlist columns. Authed.

``GET ""`` lists yours; ``POST ""`` ``{name, columns}`` (201); ``PATCH /{id}``
``{name?, columns?}``; ``DELETE /{id}`` (204; lists that used it fall back to
the default columns). Columns come from the allow-list in
``services/watchlists.COLUMN_KEYS``; another user's set is 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import ColumnSet
from stockviz.schemas import ColumnSetIn, ColumnSetOut, ColumnSetPatch
from stockviz.services import watchlists as svc

router = APIRouter(prefix="/v1/column-sets", tags=["watchlists"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(row: ColumnSet) -> ColumnSetOut:
    assert row.id is not None
    return ColumnSetOut(
        id=row.id,
        name=row.name,
        columns=[c for c in row.columns if c in svc.COLUMN_KEYS],  # type: ignore[misc]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[ColumnSetOut])
def list_column_sets(session: SessionDep, user_id: UserIdDep) -> list[ColumnSetOut]:
    return [_out(row) for row in svc.column_sets_of(session, user_id)]


@router.post("", response_model=ColumnSetOut, status_code=status.HTTP_201_CREATED)
def create_column_set(body: ColumnSetIn, session: SessionDep, user_id: UserIdDep) -> ColumnSetOut:
    return _out(svc.create_column_set(session, user_id, body.name, body.columns))


@router.patch("/{set_id}", response_model=ColumnSetOut)
def update_column_set(
    set_id: int, body: ColumnSetPatch, session: SessionDep, user_id: UserIdDep
) -> ColumnSetOut:
    return _out(
        svc.update_column_set(session, user_id, set_id, fields=body.model_dump(exclude_unset=True))
    )


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_column_set(set_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    svc.delete_column_set(session, user_id, set_id)
