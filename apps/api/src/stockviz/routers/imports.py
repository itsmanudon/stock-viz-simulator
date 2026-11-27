"""`/v1/books/{id}/imports` and opening lots (A5.3, M10.2 CSV part). Authed.

An imported book takes a Zerodha Console tradebook CSV in two steps, with
nothing kept between them:

- ``POST /imports/preview`` (``text/csv`` body, at most 2 MB): what the file
  holds and what commit would post: the matched columns (and unmatched
  headers), the first parsed trades, every rejected row with its reason (row
  number and field only), duplicates, unmatched instruments, sells that need
  an opening lot and basis-uncertain trades. Nothing is stored. The format
  is ``format_status: "unconfirmed"`` (see ``services/imports/columns.py``).
- ``POST /imports/commit?file_sha256=`` the same body again; 409 when its
  hash differs from the previewed one. Stores the new fills and one batch
  (hash and counts; never the file, its name or a client id) and rebuilds
  the book. 200 with ``batch: null`` when nothing is new.
- ``GET /imports``: the batches, opening lots and the sells still waiting.
- ``DELETE /imports/{batch_id}`` (204): the batch, its fills and their
  trades; the book is rebuilt.
- ``POST /opening-lots`` (201) and ``DELETE /opening-lots/{id}`` (204).

A6.11: preview and commit take ``map`` (``auto``, the default, detects the
map from the header row; or a built-in name such as ``dhan_tradebook_v1``)
or ``custom_map`` (the caller's saved map, ``/v1/import-maps``). Commit must
name the same map as the preview. A broker map into a book of the other
market is 409.

Another user's book is 404, a paper book 409, an archived one 409 for
writes. Request bodies are never logged; errors name no cell value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.schemas import (
    ImportCommitOut,
    ImportPreviewOut,
    ImportsOut,
    OpeningLotIn,
    OpeningLotOut,
)
from stockviz.services.imports import book as svc
from stockviz.services.imports.parse import MAX_FILE_BYTES

router = APIRouter(prefix="/v1/books/{book_id}", tags=["imports"])

SessionDep = Annotated[Session, Depends(get_session)]

CSV_TYPES = frozenset(
    {"text/csv", "text/plain", "application/csv", "application/vnd.ms-excel",
     "application/octet-stream"}
)  # fmt: skip


async def csv_body(request: Request) -> bytes:
    """The raw CSV, read under the cap (413 past it). Never logged."""
    kind = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if kind not in CSV_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the tradebook as a text/csv body"
        )
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 2 MB")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 2 MB")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    return body


CsvBody = Annotated[bytes, Depends(csv_body)]
CSV_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {"text/csv": {"schema": {"type": "string", "maxLength": MAX_FILE_BYTES}}},
    }
}


MapQuery = Annotated[
    str, Query(alias="map", max_length=40, pattern="^[a-z0-9_]+$", description="auto or a map")
]
CustomMapQuery = Annotated[int | None, Query(gt=0, description="A saved column map's id")]


def _now() -> datetime:
    return datetime.now(UTC)


def _http(exc: Exception) -> HTTPException:
    code = {
        svc.ImportNotAllowed: status.HTTP_409_CONFLICT,
        svc.ImportMismatch: status.HTTP_409_CONFLICT,
        svc.ImportInvalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
        svc.ImportThrottled: status.HTTP_429_TOO_MANY_REQUESTS,
        svc.ImportNotFound: status.HTTP_404_NOT_FOUND,
    }[type(exc)]
    return HTTPException(code, str(exc))


ERRORS = (
    svc.ImportNotAllowed,
    svc.ImportMismatch,
    svc.ImportInvalid,
    svc.ImportThrottled,
    svc.ImportNotFound,
)


@router.post("/imports/preview", response_model=ImportPreviewOut, openapi_extra=CSV_OPENAPI)
def preview_import(
    book_id: int,
    body: CsvBody,
    session: SessionDep,
    user_id: UserIdDep,
    map_name: MapQuery = "auto",
    custom_map: CustomMapQuery = None,
) -> ImportPreviewOut:
    """Parse and check a tradebook. Stores nothing."""
    try:
        out = svc.preview(
            session,
            user_id,
            book_id,
            body,
            now=_now(),
            map_name=map_name,
            custom_map_id=custom_map,
        )
    except ERRORS as exc:
        session.rollback()
        raise _http(exc) from None
    return ImportPreviewOut.model_validate(out)


@router.post("/imports/commit", response_model=ImportCommitOut, openapi_extra=CSV_OPENAPI)
def commit_import(
    book_id: int,
    body: CsvBody,
    session: SessionDep,
    user_id: UserIdDep,
    file_sha256: Annotated[str, Query(min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")],
    map_name: MapQuery = "auto",
    custom_map: CustomMapQuery = None,
) -> ImportCommitOut:
    """Import the previewed file (the same bytes: its SHA-256 must match)."""
    try:
        out = svc.commit(
            session,
            user_id,
            book_id,
            body,
            file_sha256=file_sha256,
            now=_now(),
            map_name=map_name,
            custom_map_id=custom_map,
        )
    except ERRORS as exc:
        session.rollback()
        raise _http(exc) from None
    return ImportCommitOut.model_validate(out)


@router.get("/imports", response_model=ImportsOut)
def list_imports(book_id: int, session: SessionDep, user_id: UserIdDep) -> ImportsOut:
    try:
        return ImportsOut.model_validate(svc.imports_out(session, user_id, book_id))
    except ERRORS as exc:
        raise _http(exc) from None


@router.delete("/imports/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(book_id: int, batch_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    """Delete one import: its fills and trades go, and the book is rebuilt."""
    try:
        svc.delete_batch(session, user_id, book_id, batch_id, now=_now())
    except ERRORS as exc:
        session.rollback()
        raise _http(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/opening-lots", response_model=OpeningLotOut, status_code=status.HTTP_201_CREATED)
def post_opening_lot(
    book_id: int, body: OpeningLotIn, session: SessionDep, user_id: UserIdDep
) -> OpeningLotOut:
    """Shares held before the file's window; sells waiting for them post."""
    try:
        lot = svc.add_opening_lot(
            session,
            user_id,
            book_id,
            ticker=body.ticker,
            on=body.on,
            quantity=body.quantity,
            avg_price=body.avg_price,
            now=_now(),
        )
    except ERRORS as exc:
        session.rollback()
        raise _http(exc) from None
    assert lot.id is not None
    return OpeningLotOut(
        id=lot.id,
        ticker=lot.ticker,
        on=body.on,
        quantity=lot.quantity,
        avg_price=lot.price,
        created_at=lot.created_at,
    )


@router.delete("/opening-lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opening_lot(
    book_id: int, lot_id: int, session: SessionDep, user_id: UserIdDep
) -> Response:
    try:
        svc.delete_opening_lot(session, user_id, book_id, lot_id, now=_now())
    except ERRORS as exc:
        session.rollback()
        raise _http(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
