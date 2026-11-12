"""The seed universe stays well formed (Phase 6, universe expansion).

12 Nov 2026: 129 symbols added (53 NSE, 76 US), drawn from recent NIFTY 50
and S&P 100 membership and each checked against yfinance for daily bars in
the previous ten days. Not the exact current index lists.
"""

from __future__ import annotations

import json

from stockviz.services.ingest.seed import DEFAULT_COMPANIES_PATH


def _rows() -> list[dict]:
    return json.loads(DEFAULT_COMPANIES_PATH.read_text(encoding="utf-8"))


def test_tickers_are_unique_and_url_safe() -> None:
    tickers = [r["symbol"] for r in _rows()]
    assert len(tickers) == len(set(tickers))
    assert all(r["name"].strip() for r in _rows())
    # Tickers become /stocks/[ticker] paths; "&" or "/" would break them.
    assert not [t for t in tickers if any(c in t for c in "&/? #")]


def test_indian_listings_say_so() -> None:
    for row in _rows():
        if row["symbol"].endswith(".NS"):
            assert (row.get("currency"), row.get("exchange")) == ("INR", "NSE"), row


def test_both_markets_have_breadth() -> None:
    tickers = [r["symbol"] for r in _rows()]
    assert sum(t.endswith(".NS") for t in tickers) >= 50
    assert sum("." not in t or t == "BRK-B" for t in tickers) >= 100
