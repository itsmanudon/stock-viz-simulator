"""The tradebook column map (A5.3): canonical fields to header names, in one table.

**Unconfirmed.** No Zerodha page lists the Console tradebook's columns. The
default names come from a third-party guide (VestAI, "Zerodha trading
journal guide", April 2026, seen in search results on 26 Nov 2026; the page
itself returned HTTP 503), which lists: symbol, ISIN, trade date, exchange,
segment, series, trade type, auction, quantity, price, trade id, order id,
order execution time. Responses say ``format_status: "unconfirmed"`` until
the owner checks a real header row (design note, question 10). A changed
header is a one-line fix here, with a test.

Headers match case-insensitively, ignoring spaces, underscores, hyphens,
dots and slashes ("Trade Date", "trade_date" and "TRADE-DATE" are one name).
Extra columns are ignored; a missing required column rejects the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAP_NAME = "zerodha_tradebook_v1"
FORMAT_STATUS = "unconfirmed"
FORMAT_NOTE = (
    "Zerodha does not publish the tradebook's columns. This map follows a third-party "
    "description and is unconfirmed: if the columns look wrong in the preview, tell us "
    "the header row (only the header row, never the file)."
)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    field: str
    label: str
    required: bool
    aliases: tuple[str, ...]


# The one table. ``aliases`` are compared after ``normalise_header``; the
# first alias is the third-party guide's spelling.
ZERODHA_TRADEBOOK_V1: tuple[FieldSpec, ...] = (
    FieldSpec("symbol", "Symbol", True, ("symbol", "tradingsymbol", "scrip", "scripname", "stock")),
    FieldSpec("isin", "ISIN", False, ("isin", "isincode", "isinno")),
    FieldSpec("trade_date", "Trade date", True, ("tradedate", "date", "tradeday")),
    FieldSpec("exchange", "Exchange", True, ("exchange", "exch", "exchangename")),
    FieldSpec("segment", "Segment", False, ("segment", "seg")),
    FieldSpec("series", "Series", False, ("series",)),
    FieldSpec(
        "side",
        "Trade type",
        True,
        ("tradetype", "buysell", "side", "type", "transactiontype", "action", "bs"),
    ),
    FieldSpec("auction", "Auction", False, ("auction", "isauction")),
    FieldSpec(
        "quantity", "Quantity", True, ("quantity", "qty", "tradedquantity", "filledquantity")
    ),
    FieldSpec("price", "Price", True, ("price", "tradeprice", "rate", "tradedprice")),
    FieldSpec("trade_id", "Trade ID", True, ("tradeid", "tradeno", "tradenumber")),
    FieldSpec("order_id", "Order ID", False, ("orderid", "orderno", "ordernumber")),
    FieldSpec(
        "executed_at",
        "Order execution time",
        False,
        (
            "orderexecutiontime",
            "executiontime",
            "tradetime",
            "orderexecutiondatetime",
            "exectime",
            "tradedatetime",
        ),
    ),
)

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
    headers: list[str], spec: tuple[FieldSpec, ...] = ZERODHA_TRADEBOOK_V1
) -> HeaderMatch:
    """Which header each field reads. The first header that matches wins; a
    second one for the same field is listed as unmatched."""
    by_alias: dict[str, FieldSpec] = {}
    for item in spec:
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
            required=item.required,
            header=found[item.field][0] if item.field in found else None,
            index=found[item.field][1] if item.field in found else None,
        )
        for item in spec
    )
    return HeaderMatch(columns=columns, unmatched_headers=tuple(unmatched))
