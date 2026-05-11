"""Technical indicators computed over ``PriceBar`` series.

Each indicator is a pure function taking parsed ``(timestamp, close)`` pairs
(plus extras like high/low/volume when relevant) and returning a list of
``(timestamp, value)`` pairs aligned to the inputs. Leading values where the
indicator can't be computed (e.g. the first ``period - 1`` bars for an SMA)
are dropped — we return the trailing valid range only. The router stitches
multiple indicators together so the wire format is one map per name.
"""

from stockviz.services.indicators.compute import (
    IndicatorPoint,
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)

__all__ = [
    "IndicatorPoint",
    "compute_ema",
    "compute_macd",
    "compute_rsi",
    "compute_sma",
]
