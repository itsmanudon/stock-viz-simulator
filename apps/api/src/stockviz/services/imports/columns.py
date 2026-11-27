"""Tradebook column maps (A5.3, A6.11): canonical fields to header names.

One ``ColumnMap`` per broker file, each a table of fields and the header
spellings that feed them, plus the user's own maps ("Map columns yourself",
``models/import_column_map.py``) built by :func:`custom_map`.

**Every broker map is unconfirmed.** No Indian broker publishes its tradebook
header row as a sample file. Each map cites what it is built from (``source``,
with the read date), and responses say ``format_status: "unconfirmed"`` until
the owner (or a user) checks a real header row. A changed header is a
one-line fix here, with a test.

- **Zerodha** (``zerodha_tradebook_v1``, A5.3): a third-party guide (VestAI,
  "Zerodha trading journal guide", April 2026, seen in search results on
  26 Nov 2026; the page itself returned HTTP 503), which lists symbol, ISIN,
  trade date, exchange, segment, series, trade type, auction, quantity,
  price, trade id, order id, order execution time.
- **Fyers** (``fyers_tradebook_v1``): Fyers' own support article "What is the
  Trade Book and how is it different from the Order Book?"
  (https://support.fyers.in/portal/en/kb/articles/what-is-the-trade-book-and-how-is-it-different-from-the-order-book,
  read 26 Nov 2026) lists the CSV's columns: Name, Date and time, Side,
  Product type, Qty, Traded price, Total value, Segment, Exchange order ID,
  FYERS order ID. No sample file, so the Name column's format is unknown;
  there is no exchange and no trade id column.
- **Dhan** (``dhan_tradebook_v1``): no public CSV sample. The names follow
  DhanHQ's v2 trade-history API fields (``tradingSymbol``,
  ``exchangeSegment`` such as ``NSE_EQ``, ``transactionType``,
  ``tradedQuantity``, ``tradedPrice``, ``exchangeTradeId``, ``orderId``,
  ``exchangeTime``, ``isin``, ``instrument``), read from the dhan-rs mirror
  of the API types (https://docs.rs/dhan-rs/0.1.6/src/dhan_rs/types/statements.rs.html,
  26 Nov 2026; https://dhanhq.co/docs/v2/statements/ redirected to a landing
  page without them). Dhan's web report may spell them differently.
- **Upstox** (``upstox_tradebook_v1``): no public header row. Upstox's help
  centre (https://upstox.com/help-center/t-249884/, read 26 Nov 2026) says the
  trade report downloads as PDF or Excel; save the Excel as CSV. The names are
  common tradebook spellings, unchecked.
- **Angel One** (``angelone_tradebook_v1``): no Angel One page lists the
  columns. A third-party journal (JournalPlus,
  https://journalplus.co/integrations/angelone, seen in search results on
  26 Nov 2026) names Symbol, Exchange, Product, Buy/Sell, Quantity, Price and
  Order ID; dates and times are common spellings, unchecked.
- **Groww** (``groww_orders_v1``): no public header row. Groww's help page
  (https://groww.in/help/my-account/ma-others/where-can-i-get-the-transaction-history,
  read 26 Nov 2026) says only how to download the report, which is opened with
  the PAN as password; save it as CSV. Order history can hold orders that did
  not execute, so an order-status column is read when present.

Headers match case-insensitively, ignoring spaces, underscores, hyphens,
dots and slashes ("Trade Date", "trade_date" and "TRADE-DATE" are one name).
Extra columns are ignored; a missing required column rejects the file, named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

Market = Literal["in", "us"]

MAP_NAME = "zerodha_tradebook_v1"
FORMAT_STATUS = "unconfirmed"
FORMAT_NOTE = (
    "Zerodha does not publish the tradebook's columns. This map follows a third-party "
    "description and is unconfirmed: if the columns look wrong in the preview, tell us "
    "the header row (only the header row, never the file)."
)
CUSTOM_PREFIX = "custom_"
"""``import_batches.column_map`` of a batch read with a saved map: ``custom_<id>``."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    field: str
    label: str
    required: bool
    aliases: tuple[str, ...]
    # Required only when this other field is not in the file (a date can
    # come from the trade date or from the execution time).
    required_unless: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnMap:
    name: str
    broker: str
    label: str
    status: Literal["unconfirmed", "confirmed", "custom"]
    # The market a broker map reads; a custom map reads the book's market.
    market: Market | None
    fields: tuple[FieldSpec, ...]
    note: str
    source: str
    # Normalised headers that point to this broker's file when detecting.
    signature: tuple[str, ...] = ()
    default_exchange: str | None = None
    date_order: str = "auto"  # auto | day_first | month_first
    how_to: str = ""


# --- the shared fields ------------------------------------------------------------

_SYMBOL = ("symbol", "tradingsymbol", "scrip", "scripname", "stock", "stockname")
_ISIN = ("isin", "isincode", "isinno")
_DATE = ("tradedate", "date", "tradeday")
_EXCHANGE = ("exchange", "exch", "exchangename")
_SIDE = ("tradetype", "buysell", "side", "type", "transactiontype", "action", "bs")
_QTY = ("quantity", "qty", "tradedquantity", "filledquantity", "tradedqty")
_PRICE = ("price", "tradeprice", "rate", "tradedprice")
_TRADE_ID = ("tradeid", "tradeno", "tradenumber", "exchangetradeid")
_ORDER_ID = ("orderid", "orderno", "ordernumber")
_EXEC = (
    "orderexecutiontime",
    "executiontime",
    "tradetime",
    "orderexecutiondatetime",
    "exectime",
    "tradedatetime",
)
_STATUS = ("orderstatus", "status")


def _f(
    field: str,
    label: str,
    required: bool,
    aliases: tuple[str, ...],
    unless: str | None = None,
) -> FieldSpec:
    return FieldSpec(field, label, required, aliases, unless)


# The A5.3 table. ``aliases`` are compared after ``normalise_header``; the
# first alias is the third-party guide's spelling.
ZERODHA_TRADEBOOK_V1: tuple[FieldSpec, ...] = (
    _f("symbol", "Symbol", True, _SYMBOL[:5]),
    _f("isin", "ISIN", False, _ISIN),
    _f("trade_date", "Trade date", True, _DATE),
    _f("exchange", "Exchange", True, _EXCHANGE),
    _f("segment", "Segment", False, ("segment", "seg")),
    _f("series", "Series", False, ("series",)),
    _f("side", "Trade type", True, _SIDE),
    _f("auction", "Auction", False, ("auction", "isauction")),
    _f("quantity", "Quantity", True, _QTY[:4]),
    _f("price", "Price", True, _PRICE),
    _f("trade_id", "Trade ID", True, _TRADE_ID[:3]),
    _f("order_id", "Order ID", False, _ORDER_ID),
    _f("executed_at", "Order execution time", False, _EXEC),
)

ZERODHA = ColumnMap(
    name=MAP_NAME,
    broker="zerodha",
    label="Zerodha Console tradebook",
    status="unconfirmed",
    market="in",
    fields=ZERODHA_TRADEBOOK_V1,
    note=FORMAT_NOTE,
    source="VestAI 'Zerodha trading journal guide' (third party), search result 26 Nov 2026",
    signature=("tradetype", "orderexecutiontime", "auction", "series"),
    how_to=(
        "In Zerodha Console, open Reports → Tradebook, choose the equity segment and a period "
        "of up to a year, and download it as CSV."
    ),
)

DHAN = ColumnMap(
    name="dhan_tradebook_v1",
    broker="dhan",
    label="Dhan trade history",
    status="unconfirmed",
    market="in",
    fields=(
        _f("symbol", "Trading symbol", True, ("tradingsymbol", "symbol", "customsymbol", "scrip")),
        _f("isin", "ISIN", False, _ISIN),
        _f("trade_date", "Trade date", True, _DATE, unless="executed_at"),
        _f("exchange", "Exchange segment", True, ("exchangesegment", "exchange", "segment")),
        _f("segment", "Instrument", False, ("instrument", "instrumenttype")),
        _f("side", "Transaction type", True, ("transactiontype", "buysell", "side", "type")),
        _f("quantity", "Traded quantity", True, ("tradedquantity", "quantity", "qty")),
        _f("price", "Traded price", True, ("tradedprice", "price", "tradeprice")),
        _f("trade_id", "Exchange trade ID", True, ("exchangetradeid", "tradeid", "tradeno")),
        _f("order_id", "Order ID", False, ("orderid", "exchangeorderid", "orderno")),
        _f("executed_at", "Exchange time", False, ("exchangetime", "tradetime", "createtime")),
    ),
    note=(
        "Dhan does not publish its tradebook's columns. This map follows the field names of "
        "Dhan's trade-history API and is unconfirmed: if the columns look wrong, tell us the "
        "header row (only the header row, never the file), or map the columns yourself."
    ),
    source="DhanHQ v2 trade-history API fields, via docs.rs dhan-rs 0.1.6, read 26 Nov 2026",
    signature=("exchangesegment", "exchangetradeid", "tradedquantity", "dhanclientid"),
    how_to="In Dhan, open the trade history report for the period and download it as CSV.",
)

FYERS = ColumnMap(
    name="fyers_tradebook_v1",
    broker="fyers",
    label="Fyers trade book",
    status="unconfirmed",
    market="in",
    fields=(
        _f("symbol", "Name", True, ("name", "symbol", "tradingsymbol")),
        _f("trade_date", "Trade date", True, _DATE, unless="executed_at"),
        _f("exchange", "Exchange", False, _EXCHANGE),
        _f("segment", "Segment", False, ("segment",)),
        _f("side", "Side", True, ("side", "buysell", "transactiontype")),
        _f("quantity", "Qty", True, ("qty", "quantity", "tradedqty")),
        _f("price", "Traded price", True, ("tradedprice", "price", "tradeprice")),
        _f("trade_id", "Trade ID", False, ("tradeid", "tradenumber", "tradeno")),
        _f("order_id", "Exchange order ID", False, ("exchangeorderid", "fyersorderid", "orderid")),
        _f("executed_at", "Date and time", False, ("dateandtime", "datetime", "tradetime")),
    ),
    note=(
        "From Fyers' list of the trade book's columns. It has no exchange column (read from a "
        "name like NSE:SBIN-EQ) and no trade ID (StockViz derives one from each row). "
        "Unconfirmed: if the columns look wrong, tell us the header row, or map the columns "
        "yourself."
    ),
    source=(
        "support.fyers.in 'What is the Trade Book and how is it different from the Order "
        "Book?', read 26 Nov 2026"
    ),
    signature=("fyersorderid", "dateandtime", "tradedprice", "producttype", "totalvalue"),
    how_to="In Fyers Web, open Reports → Trade book, pick the dates and choose Download → CSV.",
)

UPSTOX = ColumnMap(
    name="upstox_tradebook_v1",
    broker="upstox",
    label="Upstox trade report",
    status="unconfirmed",
    market="in",
    fields=(
        _f("symbol", "Scrip name", True, ("scripname", "symbol", "scrip", "tradingsymbol")),
        _f("isin", "ISIN", False, _ISIN),
        _f("trade_date", "Trade date", True, _DATE, unless="executed_at"),
        _f("exchange", "Exchange", True, _EXCHANGE),
        _f("segment", "Segment", False, ("segment",)),
        _f("side", "Side", True, ("side", "buysell", "transactiontype", "tradetype", "type")),
        _f("quantity", "Quantity", True, ("quantity", "qty", "tradedquantity")),
        _f("price", "Price", True, ("price", "rate", "tradeprice", "tradedprice")),
        _f("trade_id", "Trade number", True, ("tradeno", "tradenum", "tradenumber", "tradeid")),
        _f("order_id", "Order number", False, ("orderno", "ordernumber", "orderid")),
        _f("executed_at", "Trade time", False, ("tradetime", "time", "executiontime")),
    ),
    note=(
        "Upstox does not publish the trade report's columns, and downloads it as Excel: save "
        "it as CSV first. This map uses common tradebook names and is unconfirmed: tell us the "
        "header row, or map the columns yourself."
    ),
    source="upstox.com/help-center/t-249884 (download steps only), read 26 Nov 2026",
    signature=("scripname", "scripcode", "tradenum"),
    how_to=(
        "In Upstox, open My account → Reports → Trade report, choose the equity segment and "
        "dates, download it as Excel and save it as CSV."
    ),
)

ANGELONE = ColumnMap(
    name="angelone_tradebook_v1",
    broker="angelone",
    label="Angel One trade book",
    status="unconfirmed",
    market="in",
    fields=(
        _f("symbol", "Symbol", True, ("symbol", "tradingsymbol", "scripname", "scrip")),
        _f("isin", "ISIN", False, _ISIN),
        _f("trade_date", "Trade date", True, _DATE, unless="executed_at"),
        _f("exchange", "Exchange", True, _EXCHANGE),
        _f("segment", "Segment", False, ("segment",)),
        _f("side", "Buy/Sell", True, ("buysell", "transactiontype", "side", "type")),
        _f("quantity", "Quantity", True, ("quantity", "qty", "tradedquantity", "filledshares")),
        _f("price", "Price", True, ("price", "tradeprice", "averageprice", "fillprice")),
        _f("trade_id", "Trade ID", False, ("tradeid", "tradeno", "fillid")),
        _f("order_id", "Order ID", False, ("orderid", "orderno", "exchangeorderid")),
        _f("executed_at", "Trade time", False, ("tradetime", "filltime", "time", "datetime")),
        _f("order_status", "Status", False, _STATUS),
    ),
    note=(
        "Angel One does not publish the trade book's columns. This map follows a third-party "
        "list (Symbol, Exchange, Product, Buy/Sell, Quantity, Price, Order ID) and is "
        "unconfirmed: tell us the header row, or map the columns yourself. Without a trade ID, "
        "StockViz derives one from each row."
    ),
    source="JournalPlus Angel One integration page (third party), search result 26 Nov 2026",
    signature=("filltime", "fillid", "filledshares"),
    how_to="In Angel One, open Reports → Trade book for the dates and download it as CSV.",
)

GROWW = ColumnMap(
    name="groww_orders_v1",
    broker="groww",
    label="Groww stock order history",
    status="unconfirmed",
    market="in",
    fields=(
        _f("symbol", "Stock name", True, ("symbol", "stockname", "scripname", "stock")),
        _f("isin", "ISIN", False, _ISIN),
        _f("trade_date", "Date", True, _DATE, unless="executed_at"),
        _f("exchange", "Exchange", True, _EXCHANGE),
        _f("side", "Type", True, ("type", "buysell", "transactiontype", "side", "ordertype")),
        _f("quantity", "Quantity", True, ("quantity", "qty", "executedquantity")),
        _f("price", "Price", True, ("price", "averageprice", "avgprice", "executedprice")),
        _f("trade_id", "Trade ID", False, ("tradeid", "tradeno")),
        _f("order_id", "Exchange order ID", False, ("exchangeorderid", "orderid", "orderno")),
        _f(
            "executed_at",
            "Execution date and time",
            False,
            ("executiondateandtime", "executiontime", "datetime", "tradetime"),
        ),
        _f("order_status", "Order status", False, _STATUS),
    ),
    note=(
        "Groww does not publish the order history's columns, and the report opens with your "
        "PAN as its password: save it as CSV first. This map is unconfirmed: tell us the header "
        "row, or map the columns yourself. Orders that did not execute are left out."
    ),
    source="groww.in help: 'Where can I get the transaction history' (no columns), 26 Nov 2026",
    signature=("stockname", "executiondateandtime", "executedquantity"),
    how_to=(
        "In Groww, open Profile → Reports → Transactions → Stocks order history, pick the dates, "
        "download it and save it as CSV."
    ),
)

MAPS: dict[str, ColumnMap] = {m.name: m for m in (ZERODHA, DHAN, FYERS, UPSTOX, ANGELONE, GROWW)}
"""Every built-in map, in the order detection prefers on a tie."""

BROKER_LABELS = {
    "zerodha": "Zerodha",
    "dhan": "Dhan",
    "fyers": "Fyers",
    "upstox": "Upstox",
    "angelone": "Angel One",
    "groww": "Groww",
    "other": "Other broker",
}

# --- "Map columns yourself" ------------------------------------------------------

CUSTOM_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("trade_date", "Trade date", False),
    ("executed_at", "Execution time", False),
    ("symbol", "Symbol", True),
    ("exchange", "Exchange", False),
    ("side", "Side (buy or sell)", True),
    ("quantity", "Quantity", True),
    ("price", "Price", True),
    ("trade_id", "Trade ID", False),
    ("order_id", "Order ID", False),
    ("isin", "ISIN", False),
)
"""The fields a user maps. A date comes from the trade date or the execution
time (one is needed); without an exchange the map's default is used (India)
or the US; without a trade id StockViz derives one from the row."""

CUSTOM_FIELD_NAMES = frozenset(f for f, _l, _r in CUSTOM_FIELDS)
INDIAN_DEFAULT_EXCHANGES = ("NSE", "BSE")


def custom_map(
    map_id: int,
    name: str,
    mapping: dict[str, str],
    *,
    default_exchange: str | None = None,
    date_order: str = "auto",
) -> ColumnMap:
    """A ColumnMap from a user's saved choice of header per field."""
    fields: list[FieldSpec] = []
    for field_name, label, required in CUSTOM_FIELDS:
        header = mapping.get(field_name)
        aliases = (normalise_header(header),) if header else ()
        unless = {"trade_date": "executed_at"}.get(field_name)
        fields.append(FieldSpec(field_name, label, required or unless is not None, aliases, unless))
    return ColumnMap(
        name=f"{CUSTOM_PREFIX}{map_id}",
        broker="other",
        label=name,
        status="custom",
        market=None,
        fields=tuple(fields),
        note="Your own map: each field reads the header you chose.",
        source="the user's own map",
        default_exchange=default_exchange,
        date_order=date_order,
    )


def with_default_exchange(column_map: ColumnMap, exchange: str | None) -> ColumnMap:
    return replace(column_map, default_exchange=exchange)


# --- matching -----------------------------------------------------------------------

_STRIP = re.compile(r"[\s_\-./]+")


def normalise_header(header: str) -> str:
    """``"Trade Date"`` -> ``"tradedate"``; also drops a UTF-8 BOM and quotes."""
    return _STRIP.sub("", header.replace("﻿", "").strip().strip('"').lower())


@dataclass(frozen=True, slots=True)
class ColumnMatch:
    field: str
    label: str
    required: bool
    header: str | None
    index: int | None


@dataclass(frozen=True, slots=True)
class HeaderMatch:
    columns: tuple[ColumnMatch, ...]
    unmatched_headers: tuple[str, ...]

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(c.field for c in self.columns if c.required and c.index is None)

    def index(self, field: str) -> int | None:
        for c in self.columns:
            if c.field == field:
                return c.index
        return None


def match_headers(
    headers: list[str], spec: tuple[FieldSpec, ...] | ColumnMap = ZERODHA_TRADEBOOK_V1
) -> HeaderMatch:
    """Which header each field reads. The first header that matches wins; a
    second one for the same field is listed as unmatched. A field required
    "unless" another is required only when that other field is absent."""
    fields = spec.fields if isinstance(spec, ColumnMap) else spec
    by_alias: dict[str, FieldSpec] = {}
    for item in fields:
        for alias in item.aliases:
            by_alias.setdefault(alias, item)
    found: dict[str, tuple[str, int]] = {}
    unmatched: list[str] = []
    for i, raw in enumerate(headers):
        name = raw.replace("﻿", "").strip()
        item = by_alias.get(normalise_header(raw))
        if item is None or item.field in found:
            if name:
                unmatched.append(name[:60])
            continue
        found[item.field] = (name[:60], i)
    columns = tuple(
        ColumnMatch(
            field=item.field,
            label=item.label,
            required=item.required
            and not (item.required_unless is not None and item.required_unless in found),
            header=found[item.field][0] if item.field in found else None,
            index=found[item.field][1] if item.field in found else None,
        )
        for item in fields
    )
    return HeaderMatch(columns=columns, unmatched_headers=tuple(unmatched))


@dataclass(frozen=True, slots=True)
class Detection:
    column_map: ColumnMap
    match: HeaderMatch
    # header: every required column found; fallback: none fits, this one
    # is closest (its missing columns are named).
    how: Literal["header", "fallback"]
    alternatives: tuple[str, ...]


def detect_map(headers: list[str]) -> Detection:
    """The built-in map a header row fits. Candidates are the maps with every
    required column present; the one with the most signature headers wins,
    then the most matched fields, then registry order (Zerodha first, as
    before A6.11). With no candidate, the map missing the fewest required
    columns is returned as ``fallback`` so the preview can name them."""
    normalised = {normalise_header(h) for h in headers}
    scored: list[tuple[int, int, int, ColumnMap, HeaderMatch]] = []
    for order, m in enumerate(MAPS.values()):
        match = match_headers(headers, m)
        hits = sum(1 for s in m.signature if s in normalised)
        matched = sum(1 for c in match.columns if c.index is not None)
        scored.append((hits, matched, -order, m, match))
    full = [s for s in scored if not s[4].missing_required]
    if full:
        full.sort(key=lambda s: (s[0], s[1], s[2]), reverse=True)
        best = full[0]
        return Detection(best[3], best[4], "header", tuple(s[3].name for s in full[1:]))
    scored.sort(key=lambda s: (-len(s[4].missing_required), s[0], s[1], s[2]), reverse=True)
    best = scored[0]
    return Detection(best[3], best[4], "fallback", ())
