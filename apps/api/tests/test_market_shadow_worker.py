"""Operational Massive shadow must never alter the persisted primary bars."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import BarRecord
from stockviz.services.ingest.providers.massive import MassiveProviderError
from stockviz.workers.market_ingest_consumer import (
    fetch_bars_for_event,
    run_massive_shadow,
)


def _bar(source: str, *, scope: SessionScope, session_date: date | None = None) -> BarRecord:
    value = Decimal("100")
    return BarRecord(
        ticker="AAPL",
        ts=datetime.combine(session_date or date(2025, 1, 2), datetime.min.time()),
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1000"),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=scope,
    )


@dataclass
class _ShadowSettings:
    massive_shadow_enabled: bool
    massive_api_key: str
    massive_shadow_lookback_days: int
    alpha_vantage_key: str


def _settings(enabled: bool) -> _ShadowSettings:
    return _ShadowSettings(
        massive_shadow_enabled=enabled,
        massive_api_key="private-test-key" if enabled else "",
        massive_shadow_lookback_days=90,
        alpha_vantage_key="",
    )


def _event(*, since: date | None = None) -> SimpleNamespace:
    since_value = datetime.combine(since, datetime.min.time()) if since is not None else None
    return SimpleNamespace(payload=SimpleNamespace(ticker="AAPL", since=since_value))


def test_shadow_disabled_never_calls_massive(monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Massive must remain disabled")

    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        fail_if_called,
    )

    assert (
        run_massive_shadow(
            "AAPL",
            [_bar("yfinance", scope=SessionScope.REGULAR)],
            since=None,
            settings=_settings(False),
        )
        is None
    )


def test_shadow_result_is_not_returned_for_persistence(monkeypatch) -> None:
    primary = [_bar("yfinance", scope=SessionScope.REGULAR)]
    candidate = [_bar("massive", scope=SessionScope.PROVIDER_DAILY)]
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_daily_bars",
        lambda *_args, **_kwargs: primary,
    )
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        lambda *_args, **_kwargs: candidate,
    )
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.get_settings",
        lambda: _settings(True),
    )

    returned = fetch_bars_for_event(_event())

    assert returned is primary
    assert {bar.source for bar in returned} == {"yfinance"}


def test_runtime_shadow_failure_logs_error_but_keeps_primary(caplog, monkeypatch) -> None:
    primary = [_bar("yfinance", scope=SessionScope.REGULAR)]
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_daily_bars",
        lambda *_args, **_kwargs: primary,
    )

    def fail(*_args, **_kwargs):
        raise MassiveProviderError("timeout")

    monkeypatch.setattr("stockviz.workers.market_ingest_consumer.fetch_massive_daily", fail)
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.get_settings",
        lambda: _settings(True),
    )

    with caplog.at_level(logging.ERROR):
        returned = fetch_bars_for_event(_event())

    assert returned is primary
    assert "Massive shadow failed" in caplog.text
    assert "AAPL" in caplog.text


def test_operational_shadow_bounds_requested_history(monkeypatch) -> None:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    captured: dict[str, date] = {}

    def fake_massive(_ticker, *, start, end, api_key):
        captured.update(start=start, end=end)
        return [_bar("massive", scope=SessionScope.PROVIDER_DAILY, session_date=today - timedelta(days=1))]

    settings = _settings(True)
    settings.massive_shadow_lookback_days = 5
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        fake_massive,
    )

    result = run_massive_shadow(
        "AAPL",
        [_bar("yfinance", scope=SessionScope.REGULAR, session_date=today - timedelta(days=1))],
        since=today - timedelta(days=30),
        settings=settings,
    )

    assert result is not None
    assert captured == {"start": today - timedelta(days=5), "end": today}
