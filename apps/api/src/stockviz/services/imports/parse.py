"""Read a tradebook CSV into typed rows (A5.3). Pure: no database, no logging.

**Privacy.** These are personal financial records. Nothing here logs, and
every problem names a row number and a field, never a cell's value: the
reasons are fixed strings. Row numbers count the header as row 1, as a
spreadsheet shows them.

**Dates.** Zerodha lets users change Console's date format (support page,
read 26 Nov 2026), so the parser accepts ISO dates (``2025-04-01``), dates
with month names (``01-Apr-2025``, ``1 Apr 2025``) and numeric dates with
``/``, ``-`` or ``.``. A numeric date like ``03/04/2025`` is read day-first
or month-first only when the file itself says which: a row with a first
part over 12 (``13/04/2025``) shows day-first, one with a second part over
12 shows month-first. When the file shows neither, or both, every row whose
day and month can't be told apart is rejected rather than guessed. Times
are IST unless they carry an offset; they are stored as naive UTC, like the
ledger. A row without an execution time is placed at the start of its trade
date (IST) and marked ``time_known = False``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from stockviz.services.imports.columns import ZERODHA_TRADEBOOK_V1, HeaderMatch, match_headers

MAX_FILE_BYTES = 2 * 1024 * 1024
"""The importer's cap (design note: 2 MB, to be checked against a real
year-long file before it is fixed)."""
MAX_ROWS = 20_000

IST = timezone(timedelta(hours=5, minutes=30))

EQUITY_EXCHANGES = {"NSE": "XNSE", "BSE": "XBOM"}
OTHER_EXCHANGES = frozenset({"NFO", "BFO", "MCX", "CDS", "BCD", "NCO", "NCDEX", "MCXSX"})
EQUITY_SEGMENTS = frozenset({"EQ", "EQUITY", "CASH", "CM", "EQCASH", "EQUITYCASH"})
OTHER_SEGMENTS = frozenset(
    {
        "FO", "F&O", "FNO", "NFO", "BFO", "DERIVATIVES", "FUT", "OPT", "FUTURES", "OPTIONS",
        "CDS", "CD", "CURRENCY", "COM", "MCX", "COMMODITY", "COMMODITIES",
    }
)  # fmt: skip

KIND_REJECTED = "rejected"
KIND_SEGMENT = "segment"

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}


class FileRejected(Exception):
    """The whole file can't be read. The message names no cell value."""


@dataclass(frozen=True, slots=True)
class ParsedRow:
    row: int
    symbol: str
    isin: str | None
    exchange: str
    venue: str
    segment: str | None
    series: str | None
    side: str
    auction: bool
    quantity: Decimal
    price: Decimal
    trade_id: str
    order_id: str | None
    trade_date: date
    executed_at: datetime  # naive UTC
    time_known: bool


@dataclass(frozen=True, slots=True)
class RowProblem:
    row: int
    kind: str  # rejected | segment
    reason: str
    field: str | None = None


@dataclass(slots=True)
class ParsedFile:
    sha256: str
    header: HeaderMatch
    rows_total: int
    rows: list[ParsedRow] = field(default_factory=list)
    problems: list[RowProblem] = field(default_factory=list)
    date_order: str = "none"  # iso | day_first | month_first | ambiguous | conflicting | none


def file_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def decode(body: bytes) -> str:
    if body[:4] == b"PK\x03\x04":
        raise FileRejected(
            "This looks like an XLSX workbook. Download the tradebook as CSV and upload that."
        )
    if b"\x00" in body[:4096]:
        raise FileRejected("This is not a text CSV file.")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return body.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise FileRejected("The file is not UTF-8 text.") from exc


def _reader(text: str) -> list[list[str]]:
    sample = text[:4096]
    delimiter = ","
    counts = {d: sample.count(d) for d in (",", ";", "\t")}
    if counts[","] == 0 and max(counts.values()) > 0:
        delimiter = max(counts, key=lambda d: counts[d])
    try:
        return list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise FileRejected("The CSV could not be read (a quote is not closed).") from exc


# --- dates ---------------------------------------------------------------------

_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")
_DAY_MON = re.compile(r"^(\d{1,2})[-/. ]([A-Za-z]{3,9})[-/. ,]+(\d{2}|\d{4})$")
_MON_DAY = re.compile(r"^([A-Za-z]{3,9})[ .-](\d{1,2}),?[ .-](\d{4})$")
_TIME = re.compile(
    r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*([AaPp][Mm])?\s*(Z|[+-]\d{2}:?\d{2})?$"
)


def _year(text: str) -> int:
    y = int(text)
    return 2000 + y if y < 100 else y


def _month(name: str) -> int | None:
    return MONTHS.get(name[:3].lower())


def _numeric_parts(text: str) -> tuple[int, int] | None:
    m = _NUMERIC.match(text.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def infer_date_order(samples: list[str]) -> str:
    """What the file's numeric dates say: day_first, month_first, conflicting,
    ambiguous (numeric dates, no evidence), iso or none."""
    day_first = month_first = False
    numeric = iso = False
    for text in samples:
        parts = _numeric_parts(text)
        if parts is None:
            if _ISO.match(text.strip()):
                iso = True
            continue
        numeric = True
        a, b = parts
        if a > 12 >= b:
            day_first = True
        elif b > 12 >= a:
            month_first = True
    if day_first and month_first:
        return "conflicting"
    if day_first:
        return "day_first"
    if month_first:
        return "month_first"
    if numeric:
        return "ambiguous"
    return "iso" if iso else "none"


class _DateError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_date(text: str, order: str) -> date:
    s = text.strip()
    try:
        if m := _ISO.match(s):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _DAY_MON.match(s):
            month = _month(m.group(2))
            if month is None:
                raise _DateError("the date is not a date")
            return date(_year(m.group(3)), month, int(m.group(1)))
        if m := _MON_DAY.match(s):
            month = _month(m.group(1))
            if month is None:
                raise _DateError("the date is not a date")
            return date(int(m.group(3)), month, int(m.group(2)))
        if m := _NUMERIC.match(s):
            a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            if a > 12 >= b:
                return date(y, b, a)
            if b > 12 >= a:
                return date(y, a, b)
            if a == b:
                return date(y, a, a)
            if order == "day_first":
                return date(y, b, a)
            if order == "month_first":
                return date(y, a, b)
            raise _DateError(
                "the date is ambiguous: day and month can't be told apart in this file"
            )
    except ValueError as exc:
        if isinstance(exc, _DateError):
            raise
        raise _DateError("the date is not a real calendar date") from exc
    raise _DateError("the date is not in a format StockViz reads")


def _split_datetime(text: str) -> tuple[str | None, str | None]:
    s = text.strip()
    if not s:
        return None, None
    if "T" in s and _ISO.match(s.split("T", 1)[0]):
        d, t = s.split("T", 1)
        return d, t
    parts = s.split()
    if len(parts) == 1:
        return (None, parts[0]) if ":" in parts[0] else (parts[0], None)
    # "01 Apr 2025 09:15:32" or "01-04-2025 09:15:32 AM"
    for i, token in enumerate(parts):
        if ":" in token:
            return (" ".join(parts[:i]) or None), " ".join(parts[i:])
    return " ".join(parts), None


def parse_time(text: str) -> tuple[time, timezone | None]:
    m = _TIME.match(text.strip())
    if not m:
        raise _DateError("the execution time is not a time")
    hour, minute, second = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    meridiem = m.group(4)
    if meridiem:
        if not 1 <= hour <= 12:
            raise _DateError("the execution time is not a time")
        hour = hour % 12 + (12 if meridiem.lower() == "pm" else 0)
    if hour > 23 or minute > 59 or second > 59:
        raise _DateError("the execution time is not a time")
    zone: timezone | None = None
    if offset := m.group(5):
        if offset == "Z":
            zone = UTC
        else:
            sign = 1 if offset[0] == "+" else -1
            digits = offset[1:].replace(":", "")
            zone = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    return time(hour, minute, second), zone


def to_naive_utc(day: date, at: time, zone: timezone | None = None) -> datetime:
    aware = datetime.combine(day, at, tzinfo=zone or IST)
    return aware.astimezone(UTC).replace(tzinfo=None)


def ist_day_start(day: date) -> datetime:
    return to_naive_utc(day, time.min)


# --- values --------------------------------------------------------------------

_SCI = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_ID_FLOAT = re.compile(r"^(\d+)\.0+$")


class _ValueError(ValueError):
    def __init__(self, reason: str, field_name: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.field = field_name


def _positive(text: str, field_name: str, *, whole: bool = False) -> Decimal:
    cleaned = text.replace(",", "").replace("₹", "").replace(" ", "").strip()
    if not cleaned:
        raise _ValueError(f"{field_name} is empty", field_name)
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise _ValueError(f"{field_name} is not a number", field_name) from exc
    if not value.is_finite() or value <= 0:
        raise _ValueError(f"{field_name} must be above zero", field_name)
    if whole and value != value.to_integral_value():
        raise _ValueError(f"{field_name} must be a whole number of shares", field_name)
    if value >= Decimal("1e12"):
        raise _ValueError(f"{field_name} is too large", field_name)
    return value


def _identifier(text: str, field_name: str, *, required: bool) -> str | None:
    s = text.strip()
    if not s:
        if required:
            raise _ValueError(f"{field_name} is empty", field_name)
        return None
    if _SCI.match(s):
        raise _ValueError(
            f"{field_name} looks rounded by a spreadsheet (scientific notation); "
            "download the CSV again without opening it in a spreadsheet",
            field_name,
        )
    if m := _ID_FLOAT.match(s):
        s = m.group(1)
    if len(s) > 40:
        raise _ValueError(f"{field_name} is too long", field_name)
    return s


def _side(text: str) -> str:
    s = text.strip().lower()
    if s in ("buy", "b"):
        return "buy"
    if s in ("sell", "s"):
        return "sell"
    raise _ValueError("trade type must be buy or sell", "side")


def _auction(text: str) -> bool:
    s = text.strip().lower()
    if s in ("", "false", "no", "n", "0"):
        return False
    if s in ("true", "yes", "y", "1"):
        return True
    raise _ValueError("auction must be true or false", "auction")


def _norm_code(text: str) -> str:
    return re.sub(r"[\s\-_]", "", text.strip().upper())


# --- the file ------------------------------------------------------------------


def parse_tradebook(body: bytes, *, today: date) -> ParsedFile:
    """Parse ``body``. Raises :class:`FileRejected` when the file as a whole
    can't be read (not CSV, no header, a required column missing)."""
    if len(body) > MAX_FILE_BYTES:
        raise FileRejected("The file is larger than 2 MB.")
    sha = file_hash(body)
    rows = _reader(decode(body))
    start = next((i for i, r in enumerate(rows) if any(c.strip() for c in r)), None)
    if start is None:
        raise FileRejected("The file is empty.")
    header = match_headers(rows[start], ZERODHA_TRADEBOOK_V1)
    out = ParsedFile(sha256=sha, header=header, rows_total=0)
    if header.missing_required:
        return out
    data = [
        (start + i + 2, r) for i, r in enumerate(rows[start + 1 :]) if any(c.strip() for c in r)
    ]
    if len(data) > MAX_ROWS:
        raise FileRejected(f"The file has more than {MAX_ROWS:,} rows.")
    out.rows_total = len(data)

    def cell(r: list[str], name: str) -> str:
        idx = header.index(name)
        if idx is None or idx >= len(r):
            return ""
        return r[idx]

    samples = [cell(r, "trade_date") for _n, r in data]
    samples += [d for _n, r in data if (d := _split_datetime(cell(r, "executed_at"))[0])]
    order = infer_date_order(samples)
    out.date_order = order

    for number, r in data:
        try:
            exchange = _norm_code(cell(r, "exchange"))
            segment_raw = _norm_code(cell(r, "segment"))
            if exchange in OTHER_EXCHANGES or segment_raw in OTHER_SEGMENTS:
                out.problems.append(
                    RowProblem(
                        number,
                        KIND_SEGMENT,
                        "F&O, currency and commodity trades are not imported yet (A6): "
                        "only equity cash trades on NSE and BSE",
                        "segment",
                    )
                )
                continue
            if exchange not in EQUITY_EXCHANGES:
                raise _ValueError("exchange must be NSE or BSE", "exchange")
            if segment_raw and segment_raw not in EQUITY_SEGMENTS:
                raise _ValueError("segment is not one StockViz knows", "segment")
            symbol = cell(r, "symbol").strip().upper()
            if not symbol:
                raise _ValueError("symbol is empty", "symbol")
            if len(symbol) > 40 or not re.match(r"^[A-Z0-9&\-.]+$", symbol):
                raise _ValueError("symbol is not a trading symbol", "symbol")
            try:
                trade_day = parse_date(cell(r, "trade_date"), order)
            except _DateError as exc:
                raise _ValueError(
                    exc.reason.replace("the date", "trade date"), "trade_date"
                ) from exc
            if trade_day.year < 2000 or trade_day > today + timedelta(days=1):
                raise _ValueError("trade date is outside the range StockViz accepts", "trade_date")
            executed, known = ist_day_start(trade_day), False
            exec_text = cell(r, "executed_at")
            if exec_text.strip():
                d_text, t_text = _split_datetime(exec_text)
                try:
                    exec_day = parse_date(d_text, order) if d_text else trade_day
                    if exec_day != trade_day:
                        raise _ValueError(
                            "execution time falls on another day than the trade date",
                            "executed_at",
                        )
                    if t_text:
                        at, zone = parse_time(t_text)
                        executed, known = to_naive_utc(trade_day, at, zone), True
                except _DateError as exc:
                    raise _ValueError(
                        exc.reason.replace("the date", "execution date").replace(
                            "the execution time", "execution time"
                        ),
                        "executed_at",
                    ) from exc
            isin_text = cell(r, "isin").strip().upper()
            series = cell(r, "series").strip().upper()[:8] or None
            row = ParsedRow(
                row=number,
                symbol=symbol,
                isin=isin_text if _ISIN.match(isin_text) else None,
                exchange=exchange,
                venue=EQUITY_EXCHANGES[exchange],
                segment=segment_raw[:16] or None,
                series=series,
                side=_side(cell(r, "side")),
                auction=_auction(cell(r, "auction")),
                quantity=_positive(cell(r, "quantity"), "quantity", whole=True),
                price=_positive(cell(r, "price"), "price"),
                trade_id=_identifier(cell(r, "trade_id"), "trade id", required=True) or "",
                order_id=_identifier(cell(r, "order_id"), "order id", required=False),
                trade_date=trade_day,
                executed_at=executed,
                time_known=known,
            )
        except _ValueError as exc:
            out.problems.append(RowProblem(number, KIND_REJECTED, exc.reason, exc.field))
            continue
        out.rows.append(row)
    return out
