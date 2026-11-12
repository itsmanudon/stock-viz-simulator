"""Phase 4.5a: London pence and FX rate age (audits MD-2, MD-7)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from stockviz.models import Dividend, FxRate, PriceBar, Symbol
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.dividends import ingest_dividends_for_ticker
from stockviz.services.ingest.fx import fetch_yfinance_fx
from stockviz.services.ingest.prices import BarRecord, upsert_bars
from stockviz.services.trading.fx import StaleFxRate, fill_rate_floor, rate_for_fill

# Wednesday 11 Nov 2026, 22:00 UTC: Tuesday's and Wednesday's sessions are complete.
NOW = datetime(2026, 11, 11, 22, tzinfo=UTC)


def _bar(ticker: str, day: date, close: str, source: str = "yfinance") -> BarRecord:
    value = Decimal(close)
    return BarRecord(
        ticker=ticker,
        ts=datetime.combine(day, datetime.min.time()),
        interval="1d",
        open=value,
        high=value * Decimal("1.01"),
        low=value * Decimal("0.99"),
        close=value,
        volume=Decimal(1000),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )


def _symbols(session: Session) -> None:
    session.add(Symbol(ticker="BARC.L", name="Barclays", exchange="LSE", currency="GBP"))
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()


def _closes(session: Session, ticker: str) -> list[Decimal]:
    rows = session.exec(
        select(PriceBar).where(col(PriceBar.ticker) == ticker).order_by(col(PriceBar.ts))
    ).all()
    return [r.close for r in rows]


def test_london_provider_bars_are_stored_in_pounds(session: Session) -> None:
    _symbols(session)
    upsert_bars(
        session,
        [_bar("BARC.L", date(2026, 11, 9), "429.65"), _bar("BARC.L", date(2026, 11, 10), "430.05")],
    )
    upsert_bars(session, [_bar("AAPL", date(2026, 11, 10), "230.00")])
    session.commit()

    assert _closes(session, "BARC.L") == [Decimal("4.2965"), Decimal("4.3005")]
    bar = session.exec(
        select(PriceBar).where(col(PriceBar.ticker) == "BARC.L").order_by(col(PriceBar.ts).desc())
    ).first()
    assert bar is not None
    assert bar.high == (Decimal("430.05") * Decimal("1.01") / 100).quantize(Decimal("0.000001"))
    assert bar.volume == 1000
    assert _closes(session, "AAPL") == [Decimal("230.00")]


def test_non_provider_rows_are_not_scaled(session: Session) -> None:
    _symbols(session)
    upsert_bars(session, [_bar("BARC.L", date(2026, 11, 10), "4.30", source="v1_csv")])
    session.commit()
    assert _closes(session, "BARC.L") == [Decimal("4.30")]


def test_london_dividends_are_stored_in_pounds(session: Session) -> None:
    _symbols(session)
    ingest_dividends_for_ticker(
        session, "BARC.L", fetch_fn=lambda _t: [(date(2026, 8, 6), Decimal("5.900000"))]
    )
    ingest_dividends_for_ticker(
        session, "AAPL", fetch_fn=lambda _t: [(date(2026, 8, 11), Decimal("0.260000"))]
    )
    session.commit()
    amounts = {d.ticker: d.amount for d in session.exec(select(Dividend)).all()}
    assert amounts == {"BARC.L": Decimal("0.059000"), "AAPL": Decimal("0.260000")}


def test_fx_ingest_drops_unusable_rates() -> None:
    frame = pd.DataFrame(
        {"Close": [1.27, float("nan"), 0.0, -1.0, 1.28]},
        index=pd.DatetimeIndex(
            [pd.Timestamp(f"2026-11-0{d}", tz="Europe/London") for d in (2, 3, 4, 5, 6)]
        ),
    )
    records = fetch_yfinance_fx("GBP", history_fn=lambda _t, _s: frame)
    assert [(r.date.day, r.usd_rate) for r in records] == [
        (2, Decimal("1.27")),
        (6, Decimal("1.28")),
    ]


def test_fx_rates_refuse_a_non_positive_rate(session: Session) -> None:
    session.add(FxRate(currency="GBP", date=date(2026, 11, 2), usd_rate=Decimal(0)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_fill_floor_is_the_session_before_the_latest() -> None:
    assert fill_rate_floor(NOW, "XNYS") == date(2026, 11, 10)
    # Monday morning New York: Friday is the latest session, Thursday the floor.
    monday = datetime(2026, 11, 9, 14, tzinfo=UTC)
    assert fill_rate_floor(monday, "XNYS") == date(2026, 11, 5)
    assert fill_rate_floor(NOW, "XNYS", settled_session=date(2026, 11, 6)) == date(2026, 11, 5)


def test_rate_for_fill_accepts_last_night_and_refuses_an_outage(session: Session) -> None:
    session.add(FxRate(currency="EUR", date=date(2026, 11, 10), usd_rate=Decimal("1.08")))
    session.commit()
    assert rate_for_fill(session, "EUR", now=NOW, venue="XETR") == Decimal("1.08")

    with pytest.raises(StaleFxRate):
        rate_for_fill(session, "EUR", now=datetime(2026, 11, 13, 22, tzinfo=UTC), venue="XETR")

    # Settling an older session judges the rate against that session.
    later = datetime(2026, 11, 13, 22, tzinfo=UTC)
    assert rate_for_fill(
        session, "EUR", now=later, venue="XETR", settled_session=date(2026, 11, 11)
    ) == Decimal("1.08")
    assert rate_for_fill(session, "USD", now=later, venue="XNYS") == Decimal(1)
