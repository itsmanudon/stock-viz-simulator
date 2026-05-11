"""Seed the ``symbols`` table from the v1 ``companies.json``.

Idempotent: an existing ticker is left untouched (we don't want a seed run to
overwrite curated sector/exchange metadata if a later phase fills it in).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from stockviz.models import Symbol

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[6]
"""parents[6] = repo root. Path: apps/api/src/stockviz/services/ingest/seed.py
              [5]    [4]  [3]      [2]      [1]    [0]"""

DEFAULT_COMPANIES_PATH = _REPO_ROOT / "companies.json"


def seed_symbols(session: Session, *, path: Path | None = None) -> int:
    """Seed the ``symbols`` table from ``companies.json``. Returns rows submitted."""

    src = path or DEFAULT_COMPANIES_PATH
    if not src.exists():
        logger.warning("seed_symbols: %s not found, nothing to seed", src)
        return 0

    raw = json.loads(src.read_text(encoding="utf-8"))
    rows = [
        {"ticker": item["symbol"], "name": item["name"]}
        for item in raw
        if "symbol" in item and "name" in item
    ]
    if not rows:
        return 0

    stmt = pg_insert(Symbol).values(rows).on_conflict_do_nothing(index_elements=["ticker"])
    session.exec(stmt)  # type: ignore[arg-type]
    session.commit()
    return len(rows)
