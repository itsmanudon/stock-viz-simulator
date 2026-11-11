"""The committed seed CSVs stay on real trading dates and split-adjusted.

Guards feature audit MD-1 (UI audit T5/T6): the v1 files had a row for every
calendar day and unadjusted split jumps. Runs the regeneration script's own
checks over the committed files, so it needs no network.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "regenerate_seed_csvs.py"
_spec = importlib.util.spec_from_file_location("regenerate_seed_csvs", _SCRIPT)
assert _spec and _spec.loader
seed_csvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_csvs)

_FILES = sorted(seed_csvs.CSV_DIR.glob("*_processed.csv"))


def test_seed_csvs_exist() -> None:
    assert len(_FILES) >= 25


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name.removesuffix("_processed.csv"))
def test_seed_csv_is_on_trading_dates_and_split_adjusted(path: Path) -> None:
    assert seed_csvs.check(seed_csvs.read(path)) == []


def test_check_catches_the_old_problems() -> None:
    rows = [
        ["2024-06-07", "1200", "1210", "1190", "1208.88", "1"],
        ["2024-06-08", "121", "122", "120", "121.79", "1"],  # Saturday, unadjusted split
    ]
    problems = " ".join(seed_csvs.check(rows))
    assert "weekend" in problems
    assert "split-like jump" in problems
