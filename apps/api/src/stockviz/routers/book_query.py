"""The ``?book=`` query parameter every book-scoped route takes (A5.1).

Absent means the user's default book. The service layer resolves it through
``services/trading/books.py::resolve_book``; ``main.py`` turns
``BookNotFound`` into 404 and ``BookNotWritable`` into 409.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Query

BookQuery = Annotated[
    int | None,
    Query(
        alias="book",
        ge=1,
        description="Book id (A5.1). Omit for the default book; another user's book is 404.",
    ),
]


BookOrAllQuery = Annotated[
    str | None,
    Query(
        alias="book",
        pattern=r"^(all|[1-9][0-9]{0,17})$",
        description=(
            "Book id, or `all` for every book summed in the display currency (A5.2). "
            "Omit for the default book; another user's book is 404."
        ),
    ),
]
"""Read routes with a combined view (portfolio, overview, analytics, history,
trades, orders) take ``all`` as well as an id."""


def parse_book(value: str | None) -> int | Literal["all"] | None:
    """``"all"`` stays ``"all"``; an id becomes an int; absent stays None."""
    if value is None:
        return None
    if value == "all":
        return "all"
    return int(value)
