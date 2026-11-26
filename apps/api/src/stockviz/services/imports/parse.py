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

**Maps (A6.11).** The file is read with one ``ColumnMap``
(``services/imports/columns.py``): a broker's, or the user's own. A map
without a trade-date column takes the date from the execution time. Without
an exchange column the exchange comes from a ``NSE:SBIN-EQ`` style symbol,
else the map's default exchange. A compound code such as Dhan's ``NSE_EQ``
splits into exchange and segment. Without a trade id (Fyers, Angel One,
Groww) the row gets a derived one, ``sv-`` and a hash of its parsed fields
and its occurrence in the file, so the same file imported twice dedupes. An
order-status column, when present, leaves out orders that did not execute.

**US books (A6.11).** In a USD book (``market = "us"``) rows are US
equities: any US exchange name (or none) is stored as ``US``, times are
America/New_York, share classes become ``BRK-B``, fractional quantities are
kept, and option rows are counted and skipped like F&O.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from stockviz.services.imports.columns import (
    ZERODHA,
    ColumnMap,
    HeaderMatch,
    Market,
    match_headers,
)

MAX_FILE_BYTES = 2 * 1024 * 1024
"""The importer's cap (design note: 2 MB, to be checked against a real
year-long file before it is fixed)."""
MAX_ROWS = 20_000

IST = timezone(timedelta(hours=5, minutes=30))
NEW_YORK = ZoneInfo("America/New_York")
MARKET_TZ: dict[str, tzinfo] = {"in": IST, "us": NEW_YORK}
US_EXCHANGE = "US"
US_EXCHANGES = frozenset(
    {"", "US", "NASDAQ", "NASDAQGS", "NASDAQGM", "NASDAQCM", "NMS", "NYSE", "NYQ", "ARCA",
     "NYSEARCA", "AMEX", "NYSEAMERICAN", "NYSEMKT", "BATS", "CBOE", "IEX", "XNAS", "XNYS"}
)  # fmt: skip
EXECUTED_STATUSES = frozenset(
    {"", "EXECUTED", "COMPLETE", "COMPLETED", "FILLED", "TRADED", "SUCCESS", "SUCCESSFUL"}
)
SERIES_SUFFIX = re.compile(r"^(?P<sym>[A-Z0-9&.]+)-(?P<series>EQ|BE|BZ|SM|ST|BL|IL|E1|MF)$")
OCC_OPTION = re.compile(r"^[A-Z]{1,6}\s*\d{6}[CP]\d{8}$")

EQUITY_EXCHANGES = {"NSE": "XNSE", "BSE": "XBOM"}
OTHER_EXCHANGES = frozenset({"NFO", "BFO", "MCX", "CDS", "BCD", "NCO", "NCDEX", "MCXSX"})
EQUITY_SEGMENTS = frozenset({"EQ", "EQUITY", "CASH", "CM", "EQCASH", "EQUITYCASH"})
OTHER_SEGMENTS = frozenset(
    {
        "FO", "F&O", "FNO", "NFO", "BFO", "DERIVATIVES", "FUT", "OPT", "FUTURES", "OPTIONS",
        "CDS", "CD", "CURRENCY", "COM", "MCX", "COMMODITY", "COMMODITIES",
        "COMM", "FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK", "FUTCOM", "OPTFUT", "FUTCUR", "OPTCUR",
    }
)  # fmt: skip

KIND_REJECTED = "rejected"
KIND_SEGMENT = "segment"
KIND_NOT_EXECUTED = "not_executed"

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
    # True when the file had no trade id for the row: ``trade_id`` is derived.
    trade_id_derived: bool = False


@dataclass(frozen=True, slots=True)
class RowProblem:
    row: int
    kind: str  # rejected | segment | not_executed
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


def to_naive_utc(day: date, at: time, zone: tzinfo | None = None) -> datetime:
    aware = datetime.combine(day, at, tzinfo=zone or IST)
    return aware.astimezone(UTC).replace(tzinfo=None)


def ist_day_start(day: date) -> datetime:
    return to_naive_utc(day, time.min)


def market_day_start(day: date, market: str) -> datetime:
    return to_naive_utc(day, time.min, MARKET_TZ.get(market, IST))


def market_date(executed_at: datetime, market: str) -> date:
    """The venue date of a naive-UTC instant in the market's time zone."""
    zone = MARKET_TZ.get(market, IST)
    return executed_at.replace(tzinfo=UTC).astimezone(zone).date()


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
    if s in ("buy", "b", "bought", "purchase"):
        return "buy"
    if s in ("sell", "s", "sold", "sale"):
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


def read_rows(body: bytes) -> tuple[list[list[str]], int]:
    """The CSV's rows and the index of its header row (the first non-empty)."""
    if len(body) > MAX_FILE_BYTES:
        raise FileRejected("The file is larger than 2 MB.")
    rows = _reader(decode(body))
    start = next((i for i, r in enumerate(rows) if any(c.strip() for c in r)), None)
    if start is None:
        raise FileRejected("The file is empty.")
    return rows, start


def read_header(body: bytes) -> list[str]:
    """The header row only (map detection, "Map columns yourself")."""
    rows, start = read_rows(body)
    return rows[start]


def _split_exchange(text: str) -> tuple[str, str | None]:
    """``NSE_EQ`` -> (``NSE``, ``EQ``); ``NSE`` -> (``NSE``, None)."""
    raw = text.strip().upper()
    m = re.match(r"^([A-Z]+)[_ ]([A-Z&]+)$", raw)
    if m and (m.group(1) in EQUITY_EXCHANGES or m.group(1) in OTHER_EXCHANGES):
        return m.group(1), _norm_code(m.group(2))
    return _norm_code(raw), None


def _split_symbol(text: str) -> tuple[str | None, str, str | None]:
    """``NSE:SBIN-EQ`` -> (``NSE``, ``SBIN``, ``EQ``); a plain symbol has no prefix."""
    raw = text.strip().upper()
    if ":" not in raw:
        return None, raw, None
    exchange, _sep, rest = raw.partition(":")
    m = SERIES_SUFFIX.match(rest)
    if m:
        return _norm_code(exchange), m.group("sym"), m.group("series")
    return _norm_code(exchange), rest, None


def _us_symbol(text: str) -> str:
    return re.sub(r"[./]", "-", text.strip().upper())


def derive_trade_id(row: ParsedRow, occurrence: int) -> str:
    """A stable id for a row without one: the parsed fields and the row's
    occurrence among identical rows of the file. Never a raw cell."""
    key = "|".join(
        (
            row.exchange,
            row.symbol,
            row.side,
            format(row.quantity.normalize(), "f"),
            format(row.price.normalize(), "f"),
            row.executed_at.isoformat(),
            row.order_id or "",
            str(occurrence),
        )
    )
    return "sv-" + hashlib.sha256(key.encode()).hexdigest()[:24]


def parse_tradebook(
    body: bytes,
    *,
    today: date,
    column_map: ColumnMap = ZERODHA,
    market: Market = "in",
) -> ParsedFile:
    """Parse ``body`` with ``column_map`` for ``market``. Raises
    :class:`FileRejected` when the file as a whole can't be read (not CSV, no
    header). A missing required column leaves ``header.missing_required``
    set and no rows read."""
    sha = file_hash(body)
    rows, start = read_rows(body)
    header = match_headers(rows[start], column_map)
    out = ParsedFile(sha256=sha, header=header, rows_total=0)
    if header.missing_required:
        return out
    data = [
        (start + i + 2, r) for i, r in enumerate(rows[start + 1 :]) if any(c.strip() for c in r)
    ]
    if len(data) > MAX_ROWS:
        raise FileRejected(f"The file has more than {MAX_ROWS:,} rows.")
    out.rows_total = len(data)
    zone = MARKET_TZ[market]
    us = market == "us"
    has_trade_date = header.index("trade_date") is not None

    def cell(r: list[str], name: str) -> str:
        idx = header.index(name)
        if idx is None or idx >= len(r):
            return ""
        return r[idx]

    samples = [cell(r, "trade_date") for _n, r in data]
    samples += [d for _n, r in data if (d := _split_datetime(cell(r, "executed_at"))[0])]
    order = infer_date_order(samples)
    out.date_order = order
    if column_map.date_order in ("day_first", "month_first"):
        order = column_map.date_order
        out.date_order = order
    occurrences: dict[tuple, int] = {}

    for number, r in data:
        try:
            status = re.sub(r"[\s_\-]", "", cell(r, "order_status").strip().upper())
            if status not in EXECUTED_STATUSES:
                out.problems.append(
                    RowProblem(
                        number,
                        KIND_NOT_EXECUTED,
                        "the order did not execute (its status is not executed or complete)",
                        "order_status",
                    )
                )
                continue
            prefix, symbol_text, symbol_series = _split_symbol(cell(r, "symbol"))
            exchange, compound_segment = _split_exchange(cell(r, "exchange"))
            if not exchange and prefix:
                exchange = prefix
            segment_raw = _norm_code(cell(r, "segment")) or (compound_segment or "")
            if (
                exchange in OTHER_EXCHANGES
                or segment_raw in OTHER_SEGMENTS
                or (compound_segment in OTHER_SEGMENTS)
            ):
                out.problems.append(
                    RowProblem(
                        number,
                        KIND_SEGMENT,
                        "F&O, currency and commodity trades are not imported yet (A7): "
                        "only equity cash trades",
                        "segment",
                    )
                )
                continue
            if us:
                if exchange in EQUITY_EXCHANGES:
                    raise _ValueError(
                        "exchange is an Indian one: this book is in USD, for US trades",
                        "exchange",
                    )
                if exchange not in US_EXCHANGES:
                    raise _ValueError("exchange must be a US exchange", "exchange")
                exchange = US_EXCHANGE
                venue = US_EXCHANGE
            else:
                if not exchange:
                    exchange = column_map.default_exchange or ""
                if not exchange:
                    raise _ValueError(
                        "exchange is missing: the file has no exchange and the symbol "
                        "carries none (NSE: or BSE:)",
                        "exchange",
                    )
                if exchange not in EQUITY_EXCHANGES:
                    raise _ValueError("exchange must be NSE or BSE", "exchange")
                venue = EQUITY_EXCHANGES[exchange]
            if segment_raw and segment_raw not in EQUITY_SEGMENTS:
                raise _ValueError("segment is not one StockViz knows", "segment")
            if us:
                if " " in symbol_text.strip() or OCC_OPTION.match(symbol_text.strip()):
                    out.problems.append(
                        RowProblem(
                            number,
                            KIND_SEGMENT,
                            "option trades are not imported yet (A7): only stocks and ETFs",
                            "segment",
                        )
                    )
                    continue
                symbol = _us_symbol(symbol_text)
            else:
                symbol = symbol_text.strip().upper()
            if not symbol:
                raise _ValueError("symbol is empty", "symbol")
            pattern = r"^[A-Z0-9\-]+$" if us else r"^[A-Z0-9&\-.]+$"
            if len(symbol) > (12 if us else 40) or not re.match(pattern, symbol):
                raise _ValueError("symbol is not a trading symbol", "symbol")
            exec_text = cell(r, "executed_at")
            d_exec, t_exec = _split_datetime(exec_text) if exec_text.strip() else (None, None)
            date_text = cell(r, "trade_date") if has_trade_date else (d_exec or "")
            if not date_text.strip():
                raise _ValueError("trade date is empty", "trade_date")
            try:
                trade_day = parse_date(date_text, order)
            except _DateError as exc:
                raise _ValueError(
                    exc.reason.replace("the date", "trade date"), "trade_date"
                ) from exc
            if trade_day.year < 2000 or trade_day > today + timedelta(days=1):
                raise _ValueError("trade date is outside the range StockViz accepts", "trade_date")
            executed, known = to_naive_utc(trade_day, time.min, zone), False
            if exec_text.strip():
                try:
                    exec_day = parse_date(d_exec, order) if d_exec else trade_day
                    if exec_day != trade_day:
                        raise _ValueError(
                            "execution time falls on another day than the trade date",
                            "executed_at",
                        )
                    if t_exec:
                        at, offset = parse_time(t_exec)
                        executed, known = to_naive_utc(trade_day, at, offset or zone), True
                except _DateError as exc:
                    raise _ValueError(
                        exc.reason.replace("the date", "execution date").replace(
                            "the execution time", "execution time"
                        ),
                        "executed_at",
                    ) from exc
            isin_text = cell(r, "isin").strip().upper()
            series = (cell(r, "series").strip().upper()[:8] or symbol_series) or None
            trade_id = _identifier(cell(r, "trade_id"), "trade id", required=False)
            spec_required = any(c.field == "trade_id" and c.required for c in header.columns)
            if trade_id is None and spec_required:
                raise _ValueError("trade id is empty", "trade_id")
            row = ParsedRow(
                row=number,
                symbol=symbol,
                isin=isin_text if _ISIN.match(isin_text) else None,
                exchange=exchange,
                venue=venue,
                segment=segment_raw[:16] or None,
                series=series,
                side=_side(cell(r, "side")),
                auction=_auction(cell(r, "auction")),
                quantity=_positive(cell(r, "quantity"), "quantity", whole=not us),
                price=_positive(cell(r, "price"), "price"),
                trade_id=trade_id or "",
                order_id=_identifier(cell(r, "order_id"), "order id", required=False),
                trade_date=trade_day,
                executed_at=executed,
                time_known=known,
            )
        except _ValueError as exc:
            out.problems.append(RowProblem(number, KIND_REJECTED, exc.reason, exc.field))
            continue
        if not row.trade_id:
            key = (row.exchange, row.symbol, row.side, row.quantity, row.price, row.executed_at,
                   row.order_id)  # fmt: skip
            n = occurrences.get(key, 0)
            occurrences[key] = n + 1
            row = dataclasses.replace(row, trade_id=derive_trade_id(row, n), trade_id_derived=True)
        out.rows.append(row)
    return out
