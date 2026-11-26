"""A5.1: nothing finds a book by its user alone (design note, "One resolver").

Every ``Portfolio.user_id ==`` and ``PortfolioSnapshot.user_id ==`` (with or
without ``col(...)``) in ``src/`` is listed here with why it is allowed. A
new one fails this test: look the book up through
``services/trading/books.py::resolve_book`` (or ``owned_book`` for a row's
own book) instead, or add it here with its reason.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "stockviz"

PATTERN = re.compile(r"\b(?:col\()?(Portfolio|PortfolioSnapshot)\.user_id\)?\s*==")

ALLOWED: dict[str, tuple[int, str]] = {
    "services/trading/books.py": (
        3,
        "the resolver itself: the default book (is_default), its name, the user's books",
    ),
    "services/books/__init__.py": (
        4,
        "book CRUD: name uniqueness, the cap count, the last-book count, moving the default",
    ),
    "services/symbol_events.py": (
        1,
        "chart fill markers join across all the caller's books (A3.5; book filter optional)",
    ),
    "services/brokers/__init__.py": (
        1,
        "broker status counts the caller's imported books for a broker (A5.7; no book chosen)",
    ),
}


def _hits() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        n = len(PATTERN.findall(text))
        if n:
            found[path.relative_to(SRC).as_posix()] += n
    return found


def test_no_new_single_book_lookups() -> None:
    found = _hits()
    unexpected = {
        name: count
        for name, count in found.items()
        if name not in ALLOWED or count > ALLOWED[name][0]
    }
    assert not unexpected, (
        "A query finds a portfolio or snapshot by user alone; use resolve_book "
        f"(services/trading/books.py) or add it to ALLOWED with a reason: {unexpected}"
    )


def test_allow_list_is_not_stale() -> None:
    found = _hits()
    stale = {name: n for name, (n, _) in ALLOWED.items() if found.get(name, 0) != n}
    assert not stale, f"ALLOWED counts no longer match the code: {stale} vs {dict(found)}"


def test_pattern_catches_the_old_shapes() -> None:
    for line in (
        "select(Portfolio).where(Portfolio.user_id == user_id)",
        "select(Portfolio).where(col(Portfolio.user_id) == user_id)",
        ".where(PortfolioSnapshot.user_id == alert.user_id)",
    ):
        assert PATTERN.search(line), line
    assert not PATTERN.search("if portfolio.user_id == user_id:")
