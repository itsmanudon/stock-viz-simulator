"""Daily bars carry their own venue's session date (Phase 4 batch 4.1b).

yfinance labels a daily bar with midnight in the venue's time zone. Before
the fix the parser converted that to New York first, so every bar east of
New York was stored a day early (found in the 11 Nov 2026 cron run: BARC.L,
7203.T and RELIANCE.NS had a bar on Sunday 8 Nov and none on Friday 6 Nov).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlmodel import col, select

from stockviz.models import PriceBar, QuarantinedPriceBar
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    SOURCE_YFINANCE,
    BarRecord,
    fetch_yfinance_daily,
    upsert_bars,
)
from stockviz.services.ingest.redate import (
    misdated_tickers,
    redate_ticker,
    was_misdated,
)

FRIDAY = date(2026, 11, 6)
MONDAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 11, 22, tzinfo=UTC)


def _frame(days: list[date], zone: str, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [close] * len(days),
            "High": [close + 1] * len(days),
            "Low": [close - 1] * len(days),
            "Close": [close] * len(days),
            "Volume": [1_000] * len(days),
        },
        index=pd.DatetimeIndex([pd.Timestamp(d.isoformat(), tz=zone) for d in days]),
    )


@pytest.mark.parametrize(
    ("ticker", "zone"),
    [
        ("AAPL", "America/New_York"),
        ("SHOP.TO", "America/Toronto"),
        ("BARC.L", "Europe/London"),
        ("SAP.DE", "Europe/Berlin"),
        ("7203.T", "Asia/Tokyo"),
        ("RELIANCE.NS", "Asia/Kolkata"),
        ("BTC-USD", "UTC"),
    ],
)
def test_bar_keeps_the_venue_session_date(ticker: str, zone: str) -> None:
    bars = fetch_yfinance_daily(ticker, history_fn=lambda _t, _s: _frame([FRIDAY, MONDAY], zone))
    assert [b.ts.date() for b in bars] == [FRIDAY, MONDAY]
    assert all(b.ts.tzinfo is None for b in bars)


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [
        ("AAPL", False),
        ("SHOP.TO", False),
        ("BARC.L", True),
        ("SAP.DE", True),
        ("7203.T", True),
        ("RELIANCE.NS", True),
        ("HDFCBANK.BO", True),
    ],
)
def test_was_misdated_matches_venues_east_of_new_york(ticker: str, expected: bool) -> None:
    assert was_misdated(ticker) is expected


def _stored(ticker: str, day: date, source: str, close: str = "100") -> BarRecord:
    value = Decimal(close)
    return BarRecord(
        ticker=ticker,
        ts=datetime.combine(day, datetime.min.time()),
        interval=DAILY_INTERVAL,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal(1000),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def _seed_misdated(session) -> None:
    # The old parser's rows: each session one day early (Fri -> Thu, Mon -> Sun),
    # beside a Zerodha bulk row and a US ticker that must not change.
    upsert_bars(
        session,
        [
            _stored("RELIANCE.NS", FRIDAY - timedelta(days=1), SOURCE_YFINANCE),
            _stored("RELIANCE.NS", MONDAY - timedelta(days=1), SOURCE_YFINANCE),
            _stored("AAPL", FRIDAY, SOURCE_YFINANCE),
        ],
    )
    upsert_bars(session, [_stored("RELIANCE.NS", date(2026, 1, 30), "bulk_1min_resampled")])
    session.add(
        QuarantinedPriceBar(
            ticker="RELIANCE.NS",
            ts=datetime(2026, 11, 1),
            interval=DAILY_INTERVAL,
            open=Decimal(1),
            high=Decimal(1),
            low=Decimal(1),
            close=Decimal(1),
            volume=0,
            source=SOURCE_YFINANCE,
            reason="old",
        )
    )
    session.commit()


def _rows(session, ticker: str) -> list[tuple[date, str | None]]:
    rows = session.exec(
        select(PriceBar).where(col(PriceBar.ticker) == ticker).order_by(col(PriceBar.ts))
    ).all()
    return [(r.ts.date(), r.source) for r in rows]


def test_misdated_tickers_lists_only_non_us_yfinance_holders(session) -> None:
    _seed_misdated(session)
    assert misdated_tickers(session) == ["RELIANCE.NS"]


def test_redate_swaps_yfinance_rows_and_keeps_other_sources(session) -> None:
    _seed_misdated(session)

    result = redate_ticker(
        session,
        "RELIANCE.NS",
        history_fn=lambda _t, _s: _frame([FRIDAY, MONDAY], "Asia/Kolkata"),
        now=NOW,
    )

    assert (result.deleted_bars, result.deleted_quarantine, result.written) == (2, 1, 2)
    assert _rows(session, "RELIANCE.NS") == [
        (date(2026, 1, 30), "bulk_1min_resampled"),
        (FRIDAY, SOURCE_YFINANCE),
        (MONDAY, SOURCE_YFINANCE),
    ]
    assert _rows(session, "AAPL") == [(FRIDAY, SOURCE_YFINANCE)]
    assert session.exec(select(QuarantinedPriceBar)).all() == []


def test_redate_keeps_stored_rows_when_yfinance_returns_nothing(session) -> None:
    _seed_misdated(session)

    result = redate_ticker(
        session, "RELIANCE.NS", history_fn=lambda _t, _s: pd.DataFrame(), now=NOW
    )

    assert result.skipped
    assert len(_rows(session, "RELIANCE.NS")) == 3


def test_redate_twice_is_harmless(session) -> None:
    _seed_misdated(session)
    fetch = lambda _t, _s: _frame([FRIDAY, MONDAY], "Asia/Kolkata")  # noqa: E731
    redate_ticker(session, "RELIANCE.NS", history_fn=fetch, now=NOW)
    redate_ticker(session, "RELIANCE.NS", history_fn=fetch, now=NOW)
    assert [d for d, _ in _rows(session, "RELIANCE.NS")] == [date(2026, 1, 30), FRIDAY, MONDAY]
