"""`/v1/books` — a user's books (A5.1, M10.1).

Every other book-scoped route takes ``?book=<id>`` and resolves it through
``services/trading/books.py::resolve_book``; this router lists and manages
the books themselves. Another user's book is 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import MAX_BOOKS_PER_USER, BookKind, HolderKind
from stockviz.schemas import BookIn, BookOut, BookPatch, BooksOut
from stockviz.services.books import (
    BookConflict,
    BookInvalid,
    BookView,
    create_book,
    delete_book,
    list_books,
    update_book,
    view,
)

router = APIRouter(prefix="/v1/books", tags=["books"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(item: BookView) -> BookOut:
    book = item.book
    assert book.id is not None
    return BookOut(
        id=book.id,
        name=book.name,
        kind=BookKind(book.kind).value,  # type: ignore[arg-type]
        is_default=book.is_default,
        cash_tracked=book.cash_tracked,
        broker=book.broker,
        holder_kind=HolderKind(book.holder_kind).value,  # type: ignore[arg-type]
        holder_label=book.holder_label,
        base_currency=book.base_currency or "USD",
        archived_at=book.archived_at,
        created_at=book.created_at,
        writable=book.kind == BookKind.PAPER and book.archived_at is None,
        activity=item.activity,
    )


def _raise(exc: Exception) -> HTTPException:
    if isinstance(exc, BookConflict):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("", response_model=BooksOut)
def get_books(session: SessionDep, user_id: UserIdDep) -> BooksOut:
    """Every book, the default first (created on first use)."""
    return BooksOut(
        books=[_out(item) for item in list_books(session, user_id)], limit=MAX_BOOKS_PER_USER
    )


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def post_book(body: BookIn, session: SessionDep, user_id: UserIdDep) -> BookOut:
    """Create a book (409 past 20 or for a taken name; 422 a PAN-shaped label).

    A paper book starts with $100,000 or ₹1 crore in its base currency.
    """
    try:
        book = create_book(
            session,
            user_id=user_id,
            name=body.name,
            kind=BookKind(body.kind),
            base_currency=body.base_currency,
            holder_kind=HolderKind(body.holder_kind),
            holder_label=body.holder_label,
            broker=body.broker,
        )
    except (BookConflict, BookInvalid) as exc:
        raise _raise(exc) from exc
    return _out(view(session, book))


@router.patch("/{book_id}", response_model=BookOut)
def patch_book(book_id: int, body: BookPatch, session: SessionDep, user_id: UserIdDep) -> BookOut:
    """Rename, relabel, archive or unarchive, or make the default (409 on the rules)."""
    sent = body.model_fields_set
    kwargs: dict = {}
    if "holder_label" in sent:
        kwargs["holder_label"] = body.holder_label
    try:
        book = update_book(
            session,
            user_id=user_id,
            book_id=book_id,
            name=body.name,
            holder_kind=HolderKind(body.holder_kind) if body.holder_kind else None,
            archived=body.archived,
            make_default=body.is_default is True,
            **kwargs,
        )
    except (BookConflict, BookInvalid) as exc:
        raise _raise(exc) from exc
    return _out(view(session, book))


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_book(book_id: int, session: SessionDep, user_id: UserIdDep) -> Response:
    """Delete a book and everything in it.

    Only an empty book, or one archived first; never the default (or last) one.
    """
    try:
        delete_book(session, user_id=user_id, book_id=book_id)
    except (BookConflict, BookInvalid) as exc:
        raise _raise(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
