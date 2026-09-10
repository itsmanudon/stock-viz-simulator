"""Public indicator computation, optionally reused for identical input content.

The caller ALWAYS reads current PostgreSQL bars first. Historical corrections,
current-session changes, append/delete, and event/CLI writes change the content
key. No post-commit Redis dual write or distributed invalidation is necessary.
TTL is retention, not permission to serve an older database generation.
"""

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from stockviz.schemas import IndicatorPointOut, IndicatorsOut, MACDPointOut
from stockviz.services.cache import get_cache
from stockviz.services.indicators import compute_ema, compute_macd, compute_rsi, compute_sma


def input_key(
    namespace: str,
    ticker: str,
    interval: str,
    parsed: list[tuple[str, int | None]],
    bars: list[tuple[datetime, Decimal]],
) -> str:
    # Preserve Decimal strings and explicit timestamps, including offsets. Do
    # not hash float(close), latest-ts alone, or a presumed immutable session.
    raw = json.dumps(
        [ticker, interval, parsed, [(ts.isoformat(), str(close)) for ts, close in bars]],
        separators=(",", ":"),
    )
    return f"{namespace}:indicators:v1:{sha256(raw.encode()).hexdigest()}"


def compute_bundle(
    ticker: str,
    interval: str,
    parsed: list[tuple[str, int | None]],
    bars: list[tuple[datetime, Decimal]],
    *,
    cache=None,
) -> IndicatorsOut:
    def calculate() -> IndicatorsOut:
        series: dict[str, list[IndicatorPointOut]] = {}
        macd_points: list[MACDPointOut] | None = None
        for kind, period in parsed:
            if kind == "macd":
                macd_points = [
                    MACDPointOut(ts=p.ts, macd=p.macd, signal=p.signal, histogram=p.histogram)
                    for p in compute_macd(bars)
                ]
                continue
            assert period is not None
            if kind == "sma":
                pts = compute_sma(bars, period=period)
            elif kind == "ema":
                pts = compute_ema(bars, period=period)
            else:
                pts = compute_rsi(bars, period=period)
            series[f"{kind}_{period}"] = [IndicatorPointOut(ts=p.ts, value=p.value) for p in pts]
        return IndicatorsOut(ticker=ticker, series=series, macd=macd_points)

    cache = cache if cache is not None else get_cache()
    # Bound the pilot's cardinality/serialization work. Larger requests keep
    # their existing results and calculation path, not a weakened bar window.
    if not cache.enabled or len(bars) > 1000 or len(parsed) > 8:
        return calculate()
    return cache.get_or_set(
        input_key(cache.namespace, ticker, interval, parsed, bars),
        calculate,
        IndicatorsOut,
        ttl_seconds=300,
    )
