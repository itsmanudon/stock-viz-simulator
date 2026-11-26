"""`/v1/import-maps`: the caller's saved tradebook column maps (A6.11). Authed.

"Map columns yourself": for a file no built-in map reads, the user says
which header holds each field and saves the choice by name; preview and
commit then take ``custom_map=<id>``.

- ``GET /v1/import-maps``: the caller's maps.
- ``POST /v1/import-maps`` (201): create, or replace the map of that name.
  422 when a required field is unmapped or a header is used twice; 409 past
  20 maps.
- ``DELETE /v1/import-maps/{id}`` (204); another user's map is 404.

Only header names are stored. Request bodies are never logged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import SavedImportMapIn, SavedImportMapOut
from stockviz.services.imports import maps as svc
from stockviz.services.imports.book import (
    ImportInvalid,
    ImportNotAllowed,
    ImportNotFound,
    saved_map_out,
)

router = APIRouter(prefix="/v1/import-maps", tags=["imports"])

SessionDep = Annotated[Session, Depends(get_session)]


def _http(exc: Exception) -> HTTPException:
    code = {
        ImportInvalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
        ImportNotAllowed: status.HTTP_409_CONFLICT,
        ImportNotFound: status.HTTP_404_NOT_FOUND,
    }[type(exc)]
    return HTTPException(code, str(exc))


@router.get("", response_model=list[SavedImportMapOut])
def list_import_maps(session: SessionDep, user_id: UserIdDep) -> list[SavedImportMapOut]:
    return [
        SavedImportMapOut.model_validate(saved_map_out(r)) for r in svc.list_maps(session, user_id)
    ]


@router.post("", response_model=SavedImportMapOut, status_code=status.HTTP_201_CREATED)
def save_import_map(
    body: SavedImportMapIn, session: SessionDep, user_id: UserIdDep
) -> SavedImportMapOut:
    try:
        row = svc.save_map(
            session,
            user_id,
            name=body.name,
            mapping={str(k): v for k, v in body.mapping.items()},
            default_exchange=body.default_exchange,
            date_order=body.date_order,
            now=datetime.now(UTC).replace(tzinfo=None),
        )
    except (ImportInvalid, ImportNotAllowed) as exc:
        session.rollback()
        raise _http(exc) from None
    return SavedImportMapOut.model_validate(saved_map_out(row))


@router.delete("/{map_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import_map(map_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    try:
        svc.delete_map(session, user_id, map_id)
    except ImportNotFound as exc:
        raise _http(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
