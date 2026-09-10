"""Writer-level tests for price-bar screening (F-011).

These exercise :func:`upsert_bars` end to end against the SQLite test engine:
accepted bars land in ``price_bars``, implausible bars land in
``price_bar_quarantine``, structurally broken bars land nowhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import col, select

from stockviz.models import PriceBar, QuarantinedPriceBar
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import DAILY_INTERVAL, SOURCE_YFINANCE, BarRecord, upsert_bars

TS0 = datetime(2025, 1, 2)


def _bar(day: int, *, open="100", high="101", low="99", close="100", volume="1000000") -> BarRecord:
    return BarRecord(
        ticker="AAPL",
        ts=TS0 + timedelta(days=day),
        interval=DAILY_INTERVAL,
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        source=SOURCE_YFINANCE,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def _price_bars(session):
    return session.exec(select(PriceBar).order_by(col(PriceBar.ts))).all()


def _quarantined(session):
    return session.exec(select(QuarantinedPriceBar).order_by(col(QuarantinedPriceBar.ts))).all()


def test_valid_bars_are_written_and_nothing_is_quarantined(session):
    written = upsert_bars(session, [_bar(0), _bar(1, close="101"), _bar(2, close="100.5")])
    session.commit()

    assert written == 3
    assert len(_price_bars(session)) == 3
    assert _quarantined(session) == []


def test_a_wild_intrabar_range_is_quarantined_not_stored(session):
    written = upsert_bars(session, [_bar(0, low="100", high="400", open="100", close="390")])
    session.commit()

    assert written == 0
    assert _price_bars(session) == []
    rows = _quarantined(session)
    assert len(rows) == 1
    assert "range" in rows[0].reason
    assert rows[0].close == Decimal("390")


def test_a_structurally_broken_bar_is_dropped_entirely(session):
    written = upsert_bars(session, [_bar(0, low="102", high="101")])
    session.commit()

    assert written == 0
    assert _price_bars(session) == []
    assert _quarantined(session) == []


def test_day_over_day_spike_is_quarantined_against_the_stored_prior_close(session):
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=TS0,
            interval=DAILY_INTERVAL,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            volume=1_000_000,
            source=SOURCE_YFINANCE,
        )
    )
    session.commit()

    written = upsert_bars(session, [_bar(1, open="250", high="251", low="249", close="250")])
    session.commit()

    assert written == 0
    rows = _quarantined(session)
    assert len(rows) == 1
    assert rows[0].prev_close == Decimal("100")
    assert "prior close" in rows[0].reason


def test_upsert_bars_returns_the_count_written_to_price_bars(session):
    bars = [
        _bar(0),
        _bar(1, close="101"),
        _bar(2, low="100", high="400", close="390"),
        _bar(3, close="101"),
    ]
    written = upsert_bars(session, bars)
    session.commit()

    assert written == 3
    assert len(_price_bars(session)) == 3
    assert len(_quarantined(session)) == 1


def test_a_quarantined_bar_does_not_advance_the_running_prior_close(session):
    # bar 0 accepted at 100; bar 1 spikes to 300 (quarantined); bar 2 at 305 is
    # still compared against 100, not 300, so it is quarantined too.
    bars = [
        _bar(0, close="100"),
        _bar(1, open="300", high="301", low="299", close="300"),
        _bar(2, open="305", high="306", low="304", close="305"),
    ]
    written = upsert_bars(session, bars)
    session.commit()

    assert written == 1
    stored = _price_bars(session)
    assert [b.ts for b in stored] == [TS0]
    assert len(_quarantined(session)) == 2


def test_count_helpers_agree(session):
    upsert_bars(session, [_bar(0), _bar(1, low="100", high="500", close="480")])
    session.commit()
    assert session.exec(select(func.count()).select_from(PriceBar)).one() == 1
    assert session.exec(select(func.count()).select_from(QuarantinedPriceBar)).one() == 1
