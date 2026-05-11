"""Seed test: companies.json -> symbols table."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from stockviz.models import Symbol
from stockviz.services.ingest.seed import seed_symbols


def test_seed_symbols_inserts_rows(tmp_path: Path, session: Session) -> None:
    src = tmp_path / "companies.json"
    src.write_text(
        json.dumps(
            [
                {"symbol": "AAPL", "name": "Apple Inc."},
                {"symbol": "MSFT", "name": "Microsoft Corporation"},
            ]
        ),
        encoding="utf-8",
    )

    n = seed_symbols(session, path=src)
    assert n == 2

    tickers = sorted(t for t in session.exec(select(Symbol.ticker)).all())
    assert tickers == ["AAPL", "MSFT"]


def test_seed_symbols_is_idempotent(tmp_path: Path, session: Session) -> None:
    src = tmp_path / "companies.json"
    src.write_text(json.dumps([{"symbol": "AAPL", "name": "Apple"}]), encoding="utf-8")

    # Override the default name so we can detect whether a re-run clobbered it.
    seed_symbols(session, path=src)
    session.exec(select(Symbol).where(Symbol.ticker == "AAPL")).one().name = "CURATED NAME"
    session.commit()

    seed_symbols(session, path=src)  # second run

    row = session.exec(select(Symbol).where(Symbol.ticker == "AAPL")).one()
    # Curated name preserved (on_conflict_do_nothing means seed never overwrites).
    assert row.name == "CURATED NAME"


def test_seed_symbols_missing_file_returns_zero(tmp_path: Path, session: Session) -> None:
    assert seed_symbols(session, path=tmp_path / "nope.json") == 0
