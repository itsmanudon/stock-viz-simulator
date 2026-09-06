"""A computation-cache hit is valid only for the exact durable bar inputs."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.services.indicator_view import compute_bundle, input_key
from tests.test_indicators_router import _seed


class MemoryCache:
    enabled = True
    namespace = "stockviz:test:v1"

    def __init__(self):
        self.values = {}
        self.hits = 0
        self.misses = 0

    def get_or_set(self, key, loader, model, ttl_seconds=300):
        if key in self.values:
            self.hits += 1
            return model.model_validate_json(self.values[key])
        self.misses += 1
        result = loader()
        self.values[key] = result.model_dump_json()
        return result


def test_keys_bind_exact_decimal_timestamp_interval_names_and_version():
    bars = [(datetime(2025, 1, 1), Decimal("123456789012.123456"))]
    parsed: list[tuple[str, int | None]] = [("sma", 20)]
    args = ("stockviz:test:v1", "AAPL", "1d", parsed, bars)
    key = input_key(*args)
    assert key.startswith("stockviz:test:v1:indicators:v1:")
    assert "123456789012" not in key
    assert key != input_key("stockviz:test:v2", *args[1:])
    assert key != input_key(args[0], "NVDA", *args[2:])
    assert key != input_key(*args[:2], "1h", *args[3:])
    assert key != input_key(*args[:3], [("sma", 21)], bars)
    assert key != input_key(*args[:4], [(bars[0][0], Decimal("123456789012.123457"))])
    assert key != input_key(*args[:4], [(datetime(2025, 1, 2), bars[0][1])])


def test_hit_matches_uncached_bundle_exactly():
    bars = [(datetime(2025, 1, 1, microsecond=i), Decimal(100 + i)) for i in range(60)]
    cache = MemoryCache()
    first = compute_bundle(
        "AAPL", "1d", [("sma", 20), ("rsi", 14), ("macd", None)], bars, cache=cache
    )
    second = compute_bundle(
        "AAPL", "1d", [("sma", 20), ("rsi", 14), ("macd", None)], bars, cache=cache
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert (cache.hits, cache.misses) == (1, 1)


def test_api_cache_rechecks_bars_and_observes_historical_correction(
    session: Session, client, monkeypatch
):
    from stockviz.services import indicator_view

    cache = MemoryCache()
    monkeypatch.setattr(indicator_view, "get_cache", lambda: cache)
    _seed(session)
    path = "/v1/symbols/AAPL/indicators?names=sma_20,rsi_14,macd&limit=60"
    first = client.get(path)
    assert first.status_code == 200
    assert client.get(path).content == first.content
    assert cache.hits == 1
    # Correct an older completed bar, without changing the latest timestamp or
    # row count. Timestamp-only invalidation would incorrectly hit the cache.
    row = session.exec(select(PriceBar).order_by(col(PriceBar.ts)).limit(1)).one()
    row.close += Decimal("5")
    session.add(row)
    session.commit()
    corrected = client.get(path)
    assert corrected.content != first.content
    assert cache.misses == 2
    assert client.get(path).content == corrected.content


def test_changed_window_and_empty_series_do_not_collide():
    cache = MemoryCache()
    bars = [(datetime(2025, 1, 1, microsecond=i), Decimal(100 + i)) for i in range(25)]
    for ticker, interval, values in (
        ("AAPL", "1d", bars),
        ("AAPL", "1d", bars[1:]),
        ("AAPL", "1h", bars),
        ("NVDA", "1d", bars),
        ("AAPL", "1d", []),
    ):
        compute_bundle(ticker, interval, [("sma", 20)], values, cache=cache)
    assert cache.misses == 5


def test_event_handler_commit_changes_content_key_and_rollback_keeps_old_key(
    session, client, monkeypatch
):
    from stockviz.events.contracts.market import (
        MarketRefreshRequestedEvent,
        MarketRefreshRequestedPayload,
    )
    from stockviz.events.handlers import persist_market_refresh
    from stockviz.services import indicator_view
    from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
    from stockviz.services.ingest.prices import BarRecord

    cache = MemoryCache()
    monkeypatch.setattr(indicator_view, "get_cache", lambda: cache)
    _seed(session)
    path = "/v1/symbols/AAPL/indicators?names=sma_20&limit=60"
    original = client.get(path).content
    ts = datetime(2025, 1, 1)
    event = MarketRefreshRequestedEvent(
        event_id=uuid4(),
        occurred_at=ts,
        aggregate_id="AAPL",
        payload=MarketRefreshRequestedPayload(ticker="AAPL", reason="manual", requested_at=ts),
    )
    record = BarRecord(
        ticker="AAPL",
        ts=ts,
        interval="1d",
        open=Decimal(105),
        high=Decimal(105),
        low=Decimal(105),
        close=Decimal(105),
        volume=Decimal(1000),
        source="yfinance",
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=SessionScope.REGULAR,
    )
    assert persist_market_refresh(session, event, [record]) == "applied"
    session.rollback()
    assert client.get(path).content == original
    assert cache.hits == 1
    assert persist_market_refresh(session, event, [record]) == "applied"
    session.commit()
    assert client.get(path).content != original
    assert cache.misses == 2
