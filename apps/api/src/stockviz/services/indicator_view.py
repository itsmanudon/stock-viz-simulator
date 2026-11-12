"""Public indicator computation, optionally reused for identical input content.

The caller ALWAYS reads current PostgreSQL bars first. Historical corrections,
current-session changes, append/delete, and event/CLI writes change the content
key. No post-commit Redis dual write or distributed invalidation is necessary.
TTL is retention, not permission to serve an older database generation.

Phase 6.1: every indicator goes through ``services/indicators/engine.py``. The
caller passes OHLCV rows including the warm-up bars, and ``window_start``;
values before it are computed but not returned (audit RS-1).
"""

import json
import math
from datetime import datetime
from hashlib import sha256

from stockviz.schemas import IndicatorMetaOut, IndicatorPointOut, IndicatorsOut, MACDPointOut
from stockviz.services.cache import get_cache
from stockviz.services.indicators import engine


def input_key(
    namespace: str,
    ticker: str,
    interval: str,
    names: list[str],
    rows: list[tuple],
    window_start: datetime | None,
) -> str:
    raw = json.dumps(
        [
            ticker,
            interval,
            names,
            window_start.isoformat() if window_start else None,
            [(r[0].isoformat(), *(str(v) for v in r[1:])) for r in rows],
        ],
        separators=(",", ":"),
    )
    return f"{namespace}:indicators:v2:{sha256(raw.encode()).hexdigest()}"


def _points(series, window_start: datetime | None) -> list[IndicatorPointOut]:
    out = []
    for ts, value in series.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        stamp = ts.to_pydatetime()
        if window_start is not None and stamp < window_start:
            continue
        out.append(IndicatorPointOut(ts=stamp, value=float(value)))
    return out


def compute_bundle(
    ticker: str,
    interval: str,
    requests: list[engine.Request],
    rows: list[tuple],
    *,
    window_start: datetime | None = None,
    warmup_bars: int = 0,
    cache=None,
) -> IndicatorsOut:
    def calculate() -> IndicatorsOut:
        frame = engine.frame(rows)
        series: dict[str, list[IndicatorPointOut]] = {}
        meta: dict[str, IndicatorMetaOut] = {}
        macd_points: list[MACDPointOut] | None = None
        for req in requests:
            spec = req.spec
            meta[req.name] = IndicatorMetaOut(
                label=spec.label,
                pane=spec.pane,
                outputs=list(spec.outputs),
                params=dict(zip(spec.params, req.args, strict=True)),
                lookback=req.lookback,
                group=spec.group,
                anchored=spec.anchored,
            )
            if frame.empty:
                continue
            outputs = engine.compute(req, frame)
            if spec.key == "macd" and req.name == "macd":
                # The chart's original MACD field, kept for compatibility.
                aligned = [
                    (ts, m, s, h)
                    for ts, m, s, h in zip(
                        frame.index,
                        outputs["macd"],
                        outputs["signal"],
                        outputs["histogram"],
                        strict=True,
                    )
                    if not math.isnan(h)
                    and (window_start is None or ts.to_pydatetime() >= window_start)
                ]
                macd_points = [
                    MACDPointOut(ts=ts.to_pydatetime(), macd=m, signal=s, histogram=h)
                    for ts, m, s, h in aligned
                ]
            for output, values in outputs.items():
                key = req.name if len(spec.outputs) == 1 else f"{req.name}.{output}"
                series[key] = _points(values, window_start)
        return IndicatorsOut(
            ticker=ticker,
            series=series,
            macd=macd_points,
            meta=meta,
            warmup_bars=warmup_bars,
            window_start=window_start,
        )

    cache = cache if cache is not None else get_cache()
    # Bound the pilot's cardinality/serialization work.
    if not cache.enabled or len(rows) > 3000 or len(requests) > 8:
        return calculate()
    return cache.get_or_set(
        input_key(
            cache.namespace, ticker, interval, [r.name for r in requests], rows, window_start
        ),
        calculate,
        IndicatorsOut,
        ttl_seconds=300,
    )
