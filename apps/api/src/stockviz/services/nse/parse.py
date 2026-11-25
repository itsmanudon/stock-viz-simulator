"""Parse NSE end-of-day files into rows, and check their date (A1.1).

``parse_cm`` reads both cash bhavcopy formats, ``parse_sec_full`` the
delivery file; ``parse_any`` picks by header. Every value is kept as the
exchange printed it (``Decimal``), turnover converted to rupees.

``check_date``: every row must carry the same trading date, which must equal
the expected date (the file name's, when it has one) and be an ``XNSE``
session (special sessions count). Anything else is a ``date_mismatch``, never
a load: NSE re-publishes the previous session's file on some holidays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from stockviz.services.markets.calendar import is_session
from stockviz.services.nse.formats import (
    FileFormat,
    ParseError,
    UnrecognisedFile,
    detect_format,
    parse_decimal,
    parse_dmy_date,
    parse_int,
    parse_iso_date,
    read_table,
)

NSE_VENUE = "XNSE"
LAKH = Decimal(100_000)


@dataclass(frozen=True)
class CmRow:
    symbol: str
    series: str
    isin: str | None
    trading_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    last: Decimal | None
    prev_close: Decimal | None
    volume: int | None
    turnover: Decimal | None  # rupees
    trades: int | None


@dataclass(frozen=True)
class SecRow:
    symbol: str
    series: str
    trading_date: date
    deliverable_qty: int | None
    delivery_pct: Decimal | None
    turnover: Decimal | None = None  # rupees (the file prints lakhs); not stored


@dataclass
class ParsedFile:
    format: FileFormat
    rows: list = field(default_factory=list)  # CmRow or SecRow
    dates: frozenset[date] = frozenset()

    @property
    def trading_date(self) -> date | None:
        """The one date every row carries, or None (no rows, or several dates)."""
        return next(iter(self.dates)) if len(self.dates) == 1 else None


def _wrap(line: int, exc: ParseError) -> ParseError:
    return ParseError(f"row {line}: {exc}")


def _udiff_row(r: dict[str, str]) -> CmRow:
    return CmRow(
        symbol=r["TCKRSYMB"],
        series=r["SCTYSRS"],
        isin=r["ISIN"] or None,
        trading_date=parse_iso_date(r["TRADDT"], "TradDt"),
        open=parse_decimal(r["OPNPRIC"], "OpnPric"),
        high=parse_decimal(r["HGHPRIC"], "HghPric"),
        low=parse_decimal(r["LWPRIC"], "LwPric"),
        close=parse_decimal(r["CLSPRIC"], "ClsPric"),
        last=parse_decimal(r["LASTPRIC"], "LastPric"),
        prev_close=parse_decimal(r["PRVSCLSGPRIC"], "PrvsClsgPric"),
        volume=parse_int(r["TTLTRADGVOL"], "TtlTradgVol"),
        turnover=parse_decimal(r["TTLTRFVAL"], "TtlTrfVal"),
        trades=parse_int(r["TTLNBOFTXSEXCTD"], "TtlNbOfTxsExctd"),
    )


def _legacy_row(r: dict[str, str]) -> CmRow:
    return CmRow(
        symbol=r["SYMBOL"],
        series=r["SERIES"],
        isin=r["ISIN"] or None,
        trading_date=parse_dmy_date(r["TIMESTAMP"], "TIMESTAMP"),
        open=parse_decimal(r["OPEN"], "OPEN"),
        high=parse_decimal(r["HIGH"], "HIGH"),
        low=parse_decimal(r["LOW"], "LOW"),
        close=parse_decimal(r["CLOSE"], "CLOSE"),
        last=parse_decimal(r["LAST"], "LAST"),
        prev_close=parse_decimal(r["PREVCLOSE"], "PREVCLOSE"),
        volume=parse_int(r["TOTTRDQTY"], "TOTTRDQTY"),
        turnover=parse_decimal(r["TOTTRDVAL"], "TOTTRDVAL"),
        trades=parse_int(r["TOTALTRADES"], "TOTALTRADES"),
    )


def _sec_row(r: dict[str, str]) -> SecRow:
    return SecRow(
        symbol=r["SYMBOL"],
        series=r["SERIES"],
        trading_date=parse_dmy_date(r["DATE1"], "DATE1"),
        deliverable_qty=parse_int(r["DELIV_QTY"], "DELIV_QTY"),
        delivery_pct=parse_decimal(r["DELIV_PER"], "DELIV_PER"),
        turnover=_lakhs_to_rupees(parse_decimal(r.get("TURNOVER_LACS", ""), "TURNOVER_LACS")),
    )


def _lakhs_to_rupees(value: Decimal | None) -> Decimal | None:
    return None if value is None else value * LAKH


_ROW_READERS = {
    FileFormat.CM_UDIFF: _udiff_row,
    FileFormat.CM_LEGACY: _legacy_row,
    FileFormat.SEC_FULL: _sec_row,
}


def parse_any(text: str) -> ParsedFile:
    """Parse whichever known format the header names.

    Raises ``UnrecognisedFile`` for an unknown header and ``ParseError`` (with
    the row number, the header being row 1) for a value that cannot be read.
    """
    header, rows = read_table(text)
    fmt = detect_format(header)
    reader = _ROW_READERS[fmt]
    parsed: list = []
    for line, raw in enumerate(rows, start=2):
        try:
            parsed.append(reader(raw))
        except ParseError as exc:
            raise _wrap(line, exc) from exc
    return ParsedFile(format=fmt, rows=parsed, dates=frozenset(r.trading_date for r in parsed))


def parse_cm(text: str) -> ParsedFile:
    """A cash bhavcopy, UDiFF or legacy."""
    parsed = parse_any(text)
    if parsed.format not in (FileFormat.CM_UDIFF, FileFormat.CM_LEGACY):
        raise UnrecognisedFile(f"not a CM bhavcopy ({parsed.format})")
    return parsed


def parse_sec_full(text: str) -> ParsedFile:
    """A ``sec_bhavdata_full`` delivery file."""
    parsed = parse_any(text)
    if parsed.format is not FileFormat.SEC_FULL:
        raise UnrecognisedFile(f"not a sec_bhavdata_full file ({parsed.format})")
    return parsed


def check_date(parsed: ParsedFile, expected: date | None) -> str | None:
    """Why the file's date is not acceptable, or None when it is."""
    if not parsed.dates:
        return "no rows"
    if len(parsed.dates) > 1:
        shown = ", ".join(d.isoformat() for d in sorted(parsed.dates)[:4])
        return f"rows carry {len(parsed.dates)} dates: {shown}"
    day = next(iter(parsed.dates))
    if expected is not None and day != expected:
        return f"rows are dated {day}, the file name says {expected}"
    if not is_session(day, NSE_VENUE):
        return f"{day} is not an NSE session"
    return None
