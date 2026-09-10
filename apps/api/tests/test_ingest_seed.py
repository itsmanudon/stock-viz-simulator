"""Seed test: companies.json -> symbols table."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.ingest.backfill import _parse_csv, backfill_price_bars_from_csvs
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
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


def test_v1_csv_declares_canonical_semantics_and_preserves_decimal_volume(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "AAPL_processed.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Volume\n2024-01-02,100,101,99,100.5,1000.50\n",
        encoding="utf-8",
    )

    bar = _parse_csv(csv_path, "AAPL")[0]

    assert bar.volume == Decimal("1000.50")
    assert bar.adjustment_semantics is AdjustmentSemantics.SPLIT_ADJUSTED
    assert bar.session_scope is SessionScope.REGULAR


def test_backfill_commits_so_a_new_session_sees_bars(tmp_path: Path, engine) -> None:
    """Regression: upsert_bars no longer commits; backfill must persist the batch.

    E2E fills AAPL from these CSVs. If the session closes without commit, the
    trade page reports "No market data for AAPL".
    """
    csv_path = tmp_path / "AAPL_processed.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Volume\n2024-01-02,100,101,99,100.5,1000\n",
        encoding="utf-8",
    )
    with Session(engine) as session:
        session.add(Symbol(ticker="AAPL", name="Apple Inc."))
        session.commit()
        written = backfill_price_bars_from_csvs(session, csv_dir=tmp_path)
        assert written == {"AAPL": 1}

    with Session(engine) as session:
        bars = session.exec(select(PriceBar).where(PriceBar.ticker == "AAPL")).all()
        assert len(bars) == 1
        assert bars[0].close == Decimal("100.5")
