"""Saved column maps (A6.11): "Map columns yourself", per user.

The user names, for each field, the header of their file that holds it.
Only header names are stored (``models/import_column_map.py``); a map is
checked here before it is saved: the required fields (symbol, side,
quantity, price, and a trade date or an execution time) are mapped, no
header is used twice, and the user holds at most
``MAX_IMPORT_MAPS_PER_USER``. Nothing here logs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.models.import_column_map import (
    IMPORT_MAP_HEADER_MAX,
    MAX_IMPORT_MAPS_PER_USER,
    ImportColumnMap,
)
from stockviz.services.imports.book import ImportInvalid, ImportNotAllowed, ImportNotFound
from stockviz.services.imports.columns import CUSTOM_FIELD_NAMES, CUSTOM_FIELDS, normalise_header

REQUIRED = tuple(f for f, _label, required in CUSTOM_FIELDS if required)
LABELS = {f: label for f, label, _r in CUSTOM_FIELDS}


def clean_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """The mapping with blank entries dropped. Raises :class:`ImportInvalid`."""
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for field, header in mapping.items():
        if field not in CUSTOM_FIELD_NAMES:
            raise ImportInvalid(f"Unknown field {field!r}")
        text = (header or "").replace("﻿", "").strip()
        if not text:
            continue
        if len(text) > IMPORT_MAP_HEADER_MAX:
            raise ImportInvalid(f"The header for {LABELS[field]} is too long")
        key = normalise_header(text)
        if not key:
            raise ImportInvalid(f"The header for {LABELS[field]} is blank")
        if key in seen:
            raise ImportInvalid(
                f"{LABELS[seen[key]]} and {LABELS[field]} read the same header: pick one each"
            )
        seen[key] = field
        out[field] = text
    missing = [LABELS[f] for f in REQUIRED if f not in out]
    if "trade_date" not in out and "executed_at" not in out:
        missing.append("Trade date or Execution time")
    if missing:
        raise ImportInvalid("Map these fields: " + ", ".join(missing))
    return out


def list_maps(session: Session, user_id: int) -> list[ImportColumnMap]:
    return list(
        session.exec(
            select(ImportColumnMap)
            .where(col(ImportColumnMap.user_id) == user_id)
            .order_by(col(ImportColumnMap.name))
        ).all()
    )


def save_map(
    session: Session,
    user_id: int,
    *,
    name: str,
    mapping: dict[str, str],
    default_exchange: str | None,
    date_order: str,
    now: datetime,
) -> ImportColumnMap:
    """Create the map, or replace the caller's map of the same name. Commits."""
    clean = clean_mapping(mapping)
    name = " ".join(name.split())
    if not name:
        raise ImportInvalid("Name the map")
    row = session.exec(
        select(ImportColumnMap).where(
            col(ImportColumnMap.user_id) == user_id, col(ImportColumnMap.name) == name
        )
    ).first()
    if row is None:
        count = session.exec(
            select(func.count())
            .select_from(ImportColumnMap)
            .where(col(ImportColumnMap.user_id) == user_id)
        ).one()
        if count >= MAX_IMPORT_MAPS_PER_USER:
            raise ImportNotAllowed(f"At most {MAX_IMPORT_MAPS_PER_USER} saved maps")
        row = ImportColumnMap(user_id=user_id, name=name, mapping=clean, created_at=now)
    row.mapping = clean
    row.default_exchange = default_exchange
    row.date_order = date_order
    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_map(session: Session, user_id: int, map_id: int) -> None:
    row = session.get(ImportColumnMap, map_id)
    if row is None or row.user_id != user_id:
        raise ImportNotFound(f"Column map {map_id} not found")
    session.delete(row)
    session.commit()
