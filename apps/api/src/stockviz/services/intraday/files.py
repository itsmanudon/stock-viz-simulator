"""The owner's intraday file formats (A6.1), and which instrument each file is.

Three formats, read from the workspace note (``docs/a6-design-note.md``,
section 2), all ``date,open,high,low,close,volume`` with a header row:

- ``bulk1m``: ``<NAME>_bulk_data.csv``, 1-minute bars, the date with its
  offset (``2023-01-31 09:15:00+05:30``). The master for Indian minutes.
- ``bulk1h``: ``<NAME>_1hr_bulk_data.csv``, hourly bars, with the offset; the
  label is the bar's open.
- ``moneycontrol``: ``<YEAR>_<NAME>_1m_MoneyControl.csv``, 1-minute bars with
  **naive** timestamps, read as IST. Reconciliation only, never stored.

The MetaTrader commodity exports are not read: their server time zone is
unknown (design note question 9). Timestamps become naive UTC instants.
Nothing here logs a cell value.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

IST_OFFSET = timedelta(hours=5, minutes=30)
HEADER = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class FileKind:
    key: str  # the CLI's --kind
    file_kind: str | None  # intraday_files.kind; None = not stored
    source: str  # intraday_bars.source
    interval: str
    minutes: int
    naive_zone_offset: timedelta | None  # how to read a naive timestamp; None = refuse it
    stored: bool


KINDS: dict[str, FileKind] = {
    "bulk1m": FileKind("bulk1m", "bulk_1m", "bulk_1m", "1m", 1, None, True),
    "bulk1h": FileKind("bulk1h", "bulk_1h", "bulk_1h", "60m", 60, None, True),
    "moneycontrol": FileKind("moneycontrol", None, "moneycontrol", "1m", 1, IST_OFFSET, False),
}

# File names -> Yahoo-style tickers. A stem is upper-cased; NIFTY50 is the
# seeded benchmark ^NSEI (one identity for Nifty 50); every other stem is
# its NSE listing or index as production names them (BANKNIFTY.NS, ...).
TICKER_ALIASES: dict[str, str] = {
    "NIFTY50": "^NSEI",
    "SENSEX": "^BSESN",
}

_MONEYCONTROL = re.compile(r"^(?:\d{4}_)?(?P<stem>.+?)_1m_MoneyControl\.csv$", re.IGNORECASE)


def file_stem(kind: FileKind, name: str) -> str | None:
    """The instrument part of a file name, or None when the name is not this kind's."""
    lower = name.lower()
    if kind.key == "bulk1h":
        return name[: -len("_1hr_bulk_data.csv")] if lower.endswith("_1hr_bulk_data.csv") else None
    if kind.key == "bulk1m":
        if lower.endswith("_1hr_bulk_data.csv") or not lower.endswith("_bulk_data.csv"):
            return None
        return name[: -len("_bulk_data.csv")]
    match = _MONEYCONTROL.match(name)
    return match.group("stem") if match else None


def ticker_for_stem(stem: str) -> str:
    """``TCS`` -> ``TCS.NS``; ``Nifty50`` / ``NIFTY50`` -> ``^NSEI``; ``BankNifty`` -> ``BANKNIFTY.NS``."""
    key = re.sub(r"[\s-]+", "", stem).upper()
    return TICKER_ALIASES.get(key, f"{key}.NS")


def discover(directory: Path, kind: FileKind) -> list[tuple[Path, str]]:
    """Every file of ``kind`` directly in ``directory`` with its ticker, by name."""
    found: list[tuple[Path, str]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        stem = file_stem(kind, path.name)
        if stem:
            found.append((path, ticker_for_stem(stem)))
    return found


@dataclass(frozen=True)
class Row:
    line: int
    ts: datetime  # naive UTC, the bar's open
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    local_ts: datetime  # naive venue-local wall time, as written


class FormatError(ValueError):
    """The file is not in the expected format (header); nothing is read."""


@dataclass
class ParseProblems:
    bad_time: int = 0
    bad_number: int = 0
    impossible: int = 0  # low > open/close, high < open/close, price <= 0
    negative_volume: int = 0
    first_lines: list[int] | None = None

    @property
    def total(self) -> int:
        return self.bad_time + self.bad_number + self.impossible + self.negative_volume

    def note(self, line: int) -> None:
        if self.first_lines is None:
            self.first_lines = []
        if len(self.first_lines) < 5:
            self.first_lines.append(line)


def _to_utc(raw: str, kind: FileKind) -> tuple[datetime, datetime] | None:
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    offset = value.utcoffset()
    if offset is None:
        if kind.naive_zone_offset is None:
            return None  # a bulk file row without its offset: refuse, never guess
        return value - kind.naive_zone_offset, value
    local = value.replace(tzinfo=None)
    return (value.astimezone(UTC).replace(tzinfo=None), local)


def read_rows(path: Path, kind: FileKind, problems: ParseProblems) -> Iterator[Row]:
    """Parse ``path``; count unreadable or impossible rows in ``problems``."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or tuple(h.strip().lower() for h in header) != HEADER:
            raise FormatError(f"{path.name}: header is not {','.join(HEADER)}")
        for line, fields in enumerate(reader, start=2):
            if not fields or (len(fields) == 1 and not fields[0].strip()):
                continue
            if len(fields) != 6:
                problems.bad_number += 1
                problems.note(line)
                continue
            stamp = _to_utc(fields[0], kind)
            if stamp is None:
                problems.bad_time += 1
                problems.note(line)
                continue
            try:
                o, h, lo, c = (Decimal(fields[i].strip()) for i in range(1, 5))
                volume = int(fields[5].strip())
            except (InvalidOperation, ValueError):
                problems.bad_number += 1
                problems.note(line)
                continue
            if not all(v.is_finite() and v > 0 for v in (o, h, lo, c)) or not (
                lo <= o <= h and lo <= c <= h
            ):
                problems.impossible += 1
                problems.note(line)
                continue
            if volume < 0:
                problems.negative_volume += 1
                problems.note(line)
                continue
            yield Row(line, stamp[0], o, h, lo, c, volume, stamp[1])
