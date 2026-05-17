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

# Path: apps/api/src/stockviz/services/ingest/seed.py
#          [4]  [3]      [2]      [1]    [0]
# parents[4] = apps/api/ — seed data lives alongside the api app.
_API_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_COMPANIES_PATH = _API_ROOT / "seed-data" / "companies.json"


def seed_symbols(session: Session, *, path: Path | None = None) -> int:
    """Seed the ``symbols`` table from ``companies.json``. Returns rows submitted."""

    src = path or DEFAULT_COMPANIES_PATH
    if not src.exists():
        logger.warning("seed_symbols: %s not found, nothing to seed", src)
        return 0

    raw = json.loads(src.read_text(encoding="utf-8"))
    rows = []
    for item in raw:
        if "symbol" not in item or "name" not in item:
            continue
        row: dict[str, object] = {"ticker": item["symbol"], "name": item["name"]}
        # currency / exchange are optional in the seed file; default to USD
        # so existing rows keep their meaning. Listed companies pin the value
        # explicitly so a future override doesn't silently break.
        row["currency"] = item.get("currency", "USD")
        if "exchange" in item:
            row["exchange"] = item["exchange"]
        rows.append(row)
    if not rows:
        return 0

    stmt = pg_insert(Symbol).values(rows).on_conflict_do_nothing(index_elements=["ticker"])
    session.exec(stmt)  # type: ignore[arg-type]
    session.commit()
    return len(rows)
