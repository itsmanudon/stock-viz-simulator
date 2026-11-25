"""NSE end-of-day file formats (A1.1): reading, header detection, values.

The format is decided by the header row's column names (any order, case and
spaces ignored), never by the file name. Three are known:

- ``nse_cm_udiff``: the cash bhavcopy since 8 Jul 2024
  (``BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip``), ``TradDt`` as
  ``YYYY-MM-DD``;
- ``nse_cm_legacy``: the cash bhavcopy before that
  (``cm<DD><MON><YYYY>bhav.csv.zip``), ``TIMESTAMP`` as ``05-JUL-2024``,
  often with a trailing empty column;
- ``nse_sec_full``: ``sec_bhavdata_full_<DDMMYYYY>.csv`` (not zipped), a space
  after every comma, ``DATE1`` as ``01-Jan-2025``, ``-`` for no delivery.

Files are read as text first (``utf-8-sig``, ``\\r\\n`` tolerated); a ``.zip``
must hold exactly one CSV.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class FileFormat(StrEnum):
    CM_UDIFF = "nse_cm_udiff"
    CM_LEGACY = "nse_cm_legacy"
    SEC_FULL = "nse_sec_full"


UNKNOWN_SOURCE = "unknown"
"""``data_files.source`` for a file whose header matched no format."""


class UnrecognisedFile(ValueError):
    """The input is not a file this module knows (header, zip layout, encoding)."""


class ParseError(ValueError):
    """A known format with a value that cannot be read."""


# Normalised header names (upper case, no whitespace) each format must carry.
REQUIRED_COLUMNS: dict[FileFormat, frozenset[str]] = {
    FileFormat.CM_UDIFF: frozenset(
        {
            "TRADDT",
            "TCKRSYMB",
            "SCTYSRS",
            "ISIN",
            "OPNPRIC",
            "HGHPRIC",
            "LWPRIC",
            "CLSPRIC",
            "LASTPRIC",
            "PRVSCLSGPRIC",
            "TTLTRADGVOL",
            "TTLTRFVAL",
            "TTLNBOFTXSEXCTD",
        }
    ),
    FileFormat.CM_LEGACY: frozenset(
        {
            "SYMBOL",
            "SERIES",
            "OPEN",
            "HIGH",
            "LOW",
            "CLOSE",
            "LAST",
            "PREVCLOSE",
            "TOTTRDQTY",
            "TOTTRDVAL",
            "TIMESTAMP",
            "TOTALTRADES",
            "ISIN",
        }
    ),
    FileFormat.SEC_FULL: frozenset(
        {"SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"}
    ),
}

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}


def read_bytes_as_text(data: bytes) -> str:
    """The CSV text of a file: a zip's single CSV, or the bytes themselves."""
    if data[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise UnrecognisedFile(f"bad zip: {exc}") from exc
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise UnrecognisedFile(f"zip holds {len(members)} files, expected one CSV")
        data = archive.read(members[0])
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnrecognisedFile(f"not UTF-8 text: {exc}") from exc


def normalise_header(name: str) -> str:
    return re.sub(r"\s+", "", name).upper()


def read_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Header (normalised) and rows keyed by it, every value stripped.

    Empty header cells (a trailing comma) and blank lines are dropped.
    """
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for raw in reader:
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        if header is None:
            header = [normalise_header(c) for c in cells]
            continue
        rows.append({name: value for name, value in zip(header, cells, strict=False) if name})
    if header is None:
        raise UnrecognisedFile("empty file")
    return [h for h in header if h], rows


def detect_format(header: list[str]) -> FileFormat:
    present = set(header)
    for fmt, required in REQUIRED_COLUMNS.items():
        if required <= present:
            return fmt
    raise UnrecognisedFile(f"header matches no known NSE format: {','.join(header[:8])}...")


def parse_decimal(value: str, column: str) -> Decimal | None:
    """A decimal, or None for an empty cell or NSE's ``-``."""
    if value in ("", "-"):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ParseError(f"{column}: not a number: {value!r}") from exc
    if not number.is_finite():
        raise ParseError(f"{column}: not a finite number: {value!r}")
    return number


def parse_int(value: str, column: str) -> int | None:
    """A whole number (``179`` or ``179.00``), or None; a fraction is an error."""
    number = parse_decimal(value, column)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise ParseError(f"{column}: not a whole number: {value!r}")
    return int(number)


def parse_iso_date(value: str, column: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ParseError(f"{column}: not a YYYY-MM-DD date: {value!r}") from exc


def parse_dmy_date(value: str, column: str) -> date:
    """``05-JUL-2024`` or ``01-Jan-2025`` (month names in English, any case)."""
    match = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", value)
    month = _MONTHS.get(match.group(2).upper()) if match else None
    if match is None or month is None:
        raise ParseError(f"{column}: not a DD-MON-YYYY date: {value!r}")
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError as exc:
        raise ParseError(f"{column}: not a date: {value!r}") from exc


_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"BhavCopy_NSE_CM_\d+_\d+_\d+_(\d{8})_F_\d+\.csv", re.I), "%Y%m%d"),
    (re.compile(r"cm(\d{2}[A-Z]{3}\d{4})bhav\.csv", re.I), "%d%b%Y"),
    (re.compile(r"sec_bhavdata_full_(\d{8})\.csv", re.I), "%d%m%Y"),
)


def date_from_file_name(name: str) -> date | None:
    """The session a file's NSE name says it is for, or None for any other name."""
    for pattern, layout in _NAME_PATTERNS:
        match = pattern.search(name)
        if match is None:
            continue
        digits = match.group(1)
        try:
            if layout == "%Y%m%d":
                return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))
            if layout == "%d%m%Y":
                return date(int(digits[4:]), int(digits[2:4]), int(digits[:2]))
            month = _MONTHS.get(digits[2:5].upper())
            return date(int(digits[5:]), month, int(digits[:2])) if month else None
        except ValueError:
            return None
    return None
