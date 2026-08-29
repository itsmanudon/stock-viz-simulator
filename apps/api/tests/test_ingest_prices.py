"""Parser tests for the price ingest layer.

These don't touch the network or the DB — both ``fetch_*`` functions take an
injectable callable so we can hand them a fixture and inspect the parsed
``BarRecord`` list.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import func
from sqlmodel import select

from stockviz.models import PriceBar
from stockviz.services.ingest.bar_semantics import (
    AdjustmentSemantics,
    SessionScope,
    completed_daily_bars,
    new_york_session_date,
    session_label,
)
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    SOURCE_ALPHA_VANTAGE,
    SOURCE_YFINANCE,
    UPSERT_CHUNK_ROWS,
    BarRecord,
    fetch_alpha_vantage_daily,
    fetch_daily_bars,
    fetch_yfinance_daily,
    upsert_bars,
)


def _yf_fixture_df() -> pd.DataFrame:
    """A 2-row yfinance-shaped DataFrame indexed by timezone-aware Timestamp."""
    return pd.DataFrame(
        {
            "Open": [180.10, 181.20],
            "High": [182.50, 183.00],
            "Low": [179.50, 180.50],
            "Close": [181.90, 182.40],
            "Volume": [50_000_000, 48_000_000],
        },
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2025-04-10", tz="America/New_York"),
                pd.Timestamp("2025-04-11", tz="America/New_York"),
            ]
        ),
    )


def test_fetch_yfinance_daily_parses_dataframe():
    bars = fetch_yfinance_daily("AAPL", history_fn=lambda ticker, start: _yf_fixture_df())
    assert len(bars) == 2
    first = bars[0]
    assert first.ticker == "AAPL"
    assert first.interval == DAILY_INTERVAL
    assert first.source == SOURCE_YFINANCE
    assert first.open == Decimal("180.1")
    assert first.close == Decimal("181.9")
    assert first.volume == Decimal("50000000")
    assert isinstance(first.volume, Decimal)
    assert first.adjustment_semantics is AdjustmentSemantics.SPLIT_ADJUSTED
    assert first.session_scope is SessionScope.REGULAR
    # tz-naive after parsing so the DB column (TIMESTAMP) stays consistent
    assert first.ts.tzinfo is None
    assert first.ts.date() == date(2025, 4, 10)


def test_fetch_yfinance_daily_returns_empty_for_empty_df():
    bars = fetch_yfinance_daily("ZZZZ", history_fn=lambda ticker, start: pd.DataFrame())
    assert bars == []


def test_fetch_yfinance_daily_skips_non_finite_latest_session_row() -> None:
    frame = _yf_fixture_df()
    frame.loc[frame.index[-1], "Close"] = float("nan")

    bars = fetch_yfinance_daily("AAPL", history_fn=lambda ticker, start: frame)

    assert [bar.ts.date() for bar in bars] == [date(2025, 4, 10)]


def test_fetch_yfinance_daily_passes_start_through():
    captured: dict = {}

    def fake_history(ticker: str, start):
        captured["ticker"] = ticker
        captured["start"] = start
        return _yf_fixture_df()

    fetch_yfinance_daily("AAPL", start=date(2025, 1, 1), history_fn=fake_history)
    assert captured == {"ticker": "AAPL", "start": date(2025, 1, 1)}


def test_session_label_is_naive_midnight() -> None:
    assert session_label(date(2025, 3, 10)) == datetime(2025, 3, 10)


def test_new_york_session_date_handles_dst() -> None:
    assert new_york_session_date(datetime(2025, 7, 1, 4, tzinfo=UTC)) == date(2025, 7, 1)
    assert new_york_session_date(datetime(2025, 1, 2, 5, tzinfo=UTC)) == date(2025, 1, 2)


def test_new_york_session_date_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        new_york_session_date(datetime(2025, 1, 2))


def test_completed_daily_bars_excludes_same_new_york_date() -> None:
    bars = [
        BarRecord(
            ticker="AAPL",
            ts=datetime(2025, 7, day),
            interval=DAILY_INTERVAL,
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("100"),
            source=SOURCE_YFINANCE,
            adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
            session_scope=SessionScope.REGULAR,
        )
        for day in (1, 2)
    ]

    completed = completed_daily_bars(bars, now=datetime(2025, 7, 2, 22, tzinfo=UTC))

    assert [bar.ts.date() for bar in completed] == [date(2025, 7, 1)]


def test_fetch_daily_bars_excludes_incomplete_same_day_bar() -> None:
    ny_today = datetime.now(ZoneInfo("America/New_York")).date()
    prior_date = ny_today - timedelta(days=1)
    frame = pd.DataFrame(
        {
            "Open": [1, 2],
            "High": [2, 3],
            "Low": [1, 2],
            "Close": [2, 3],
            "Volume": [100, 200],
        },
        index=pd.DatetimeIndex(
            [
                pd.Timestamp(prior_date, tz="America/New_York"),
                pd.Timestamp(ny_today, tz="America/New_York"),
            ]
        ),
    )

    bars = fetch_daily_bars("AAPL", history_fn=lambda _ticker, _start: frame)

    assert [bar.ts.date() for bar in bars] == [prior_date]


# ---------------------------------------------------------------------------
# Alpha Vantage
# ---------------------------------------------------------------------------


ALPHA_VANTAGE_OK = {
    "Meta Data": {"2. Symbol": "AAPL"},
    "Time Series (Daily)": {
        "2025-04-11": {
            "1. open": "181.20",
            "2. high": "183.00",
            "3. low": "180.50",
            "4. close": "182.40",
            "5. volume": "48000000",
        },
        "2025-04-10": {
            "1. open": "180.10",
            "2. high": "182.50",
            "3. low": "179.50",
            "4. close": "181.90",
            "5. volume": "50000000",
        },
    },
}

ALPHA_VANTAGE_RATE_LIMITED = {
    "Note": "Our standard API call frequency is 25 calls per day...",
}


def test_fetch_alpha_vantage_daily_parses_and_sorts_ascending():
    bars = fetch_alpha_vantage_daily("AAPL", api_key="k", fetch_fn=lambda t, k, f: ALPHA_VANTAGE_OK)
    assert len(bars) == 2
    # sorted ascending so the upsert writes in chronological order
    assert bars[0].ts == datetime(2025, 4, 10)
    assert bars[1].ts == datetime(2025, 4, 11)
    assert bars[0].source == SOURCE_ALPHA_VANTAGE
    assert bars[0].close == Decimal("181.90")
    assert bars[0].volume == Decimal("50000000")
    assert bars[0].adjustment_semantics is AdjustmentSemantics.UNADJUSTED
    assert bars[0].session_scope is SessionScope.REGULAR


def test_fetch_alpha_vantage_daily_returns_empty_on_rate_limit():
    bars = fetch_alpha_vantage_daily(
        "AAPL", api_key="k", fetch_fn=lambda t, k, f: ALPHA_VANTAGE_RATE_LIMITED
    )
    assert bars == []


def test_fetch_alpha_vantage_daily_returns_empty_without_key():
    # Crucially does not call ``fetch_fn`` — preserves the daily quota.
    called = []

    def fake_fetch(*args):
        called.append(args)
        return ALPHA_VANTAGE_OK

    bars = fetch_alpha_vantage_daily("AAPL", api_key="", fetch_fn=fake_fetch)
    assert bars == []
    assert called == []


# --- writer chunking ---------------------------------------------------------
#
# A full-history yfinance fetch is ~11k bars. price_bars binds 11 parameters per
# row, so a single multi-row INSERT of that size exceeded Postgres' 65535
# parameter ceiling and `stockviz.cli ingest` failed outright against Postgres.


def _bars(count: int) -> list[BarRecord]:
    start = datetime(1990, 1, 1)
    return [
        BarRecord(
            ticker="AAPL",
            ts=start + timedelta(days=i),
            interval=DAILY_INTERVAL,
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("100"),
            source=SOURCE_YFINANCE,
            adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
            session_scope=SessionScope.REGULAR,
        )
        for i in range(count)
    ]


class _FakePostgresSession:
    """Just enough Session for the Postgres branch of ``upsert_bars``."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def exec(self, statement):
        self.statements.append(statement)


def test_upsert_bars_chunks_large_batches_under_the_parameter_ceiling():
    session = _FakePostgresSession()
    count = UPSERT_CHUNK_ROWS * 2 + 37

    assert upsert_bars(session, _bars(count)) == count  # type: ignore[arg-type]

    assert len(session.statements) == 3, "expected one INSERT per chunk"
    # 11 bound parameters per row must stay well under Postgres' 65535 cap.
    assert UPSERT_CHUNK_ROWS * 11 < 65535


def test_upsert_bars_issues_a_single_statement_for_a_small_batch():
    session = _FakePostgresSession()

    upsert_bars(session, _bars(10))  # type: ignore[arg-type]

    assert len(session.statements) == 1


def test_upsert_bars_rejects_fractional_volume_before_numeric_migration(session):
    bar = BarRecord(
        ticker="AAPL",
        ts=datetime(2025, 1, 2),
        interval=DAILY_INTERVAL,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
        volume=Decimal("100.25"),
        source=SOURCE_YFINANCE,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )

    with pytest.raises(ValueError, match="fractional volume"):
        upsert_bars(session, [bar])


def test_upsert_bars_writes_every_row_of_a_large_batch(session):
    """SQLite path: the row-by-row branch must not drop anything either."""
    count = UPSERT_CHUNK_ROWS + 5
    assert upsert_bars(session, _bars(count)) == count
    session.commit()

    assert session.exec(select(func.count()).select_from(PriceBar)).one() == count


def test_upsert_bars_persists_provider_neutral_financial_semantics(session):
    bar = BarRecord(
        ticker="AAPL",
        ts=datetime(2025, 1, 2),
        interval=DAILY_INTERVAL,
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
        volume=Decimal("100"),
        source=SOURCE_ALPHA_VANTAGE,
        adjustment_semantics=AdjustmentSemantics.UNADJUSTED,
        session_scope=SessionScope.REGULAR,
    )

    assert upsert_bars(session, [bar]) == 1
    session.commit()

    persisted = session.get(PriceBar, (bar.ticker, bar.ts, bar.interval))
    assert persisted is not None
    assert persisted.source == SOURCE_ALPHA_VANTAGE
    assert persisted.adjustment_semantics == AdjustmentSemantics.UNADJUSTED
    assert persisted.session_scope == SessionScope.REGULAR
