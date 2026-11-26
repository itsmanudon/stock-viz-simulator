"""The ``?book=`` query parameter every book-scoped route takes (A5.1).

Absent means the user's default book. The service layer resolves it through
``services/trading/books.py::resolve_book``; ``main.py`` turns
``BookNotFound`` into 404 and ``BookNotWritable`` into 409.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

BookQuery = Annotated[
    int | None,
    Query(
        alias="book",
        ge=1,
        description="Book id (A5.1). Omit for the default book; another user's book is 404.",
    ),
]
