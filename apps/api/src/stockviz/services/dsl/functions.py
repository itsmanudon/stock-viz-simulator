"""The Rule DSL function library (A2.1).

Two kinds of function:

- **Indicators** are the registry in ``services/indicators/engine.py``, run on
  the bar frame of the expression's timeframe (daily, or weekly/monthly under
  a prefix), so a rule's RSI is the chart's RSI. Parameters are the
  registry's, by position or by name, with its defaults and bounds
  (``rsi()`` is ``rsi(14)``). A multi-output indicator picks an output with
  ``.name``: ``macd().signal``, ``bb(20, 2).lower``. ``macd``, ``adx``,
  ``stoch`` and ``supertrend`` default to their main line (``macd``,
  ``adx``, ``k``, ``line``); ``bb``, ``donchian`` and ``keltner`` must name
  one (``upper``, ``middle``, ``lower``). The registry's ``sma`` and ``ema``
  are the primitives below on ``close``: ``sma(close, 20)`` is the
  registry's ``sma_20`` exactly.
- **Primitives** take a series: ``sma ema highest lowest sum change
  pct_change abs min max count_true bars_since`` and ``rs``.

Every function declares its **lookback**, the bars it needs before its first
value, so a loader can fetch enough history (``None``: the whole history,
for ``bars_since``, ``obv`` and ``ad``). A missing input on a bar makes that
bar's result missing (NaN), never 0.

All values are float arrays; booleans are 1.0 / 0.0 / NaN (unknown).
"""

# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from stockviz.services.indicators import engine

ParamKind = Literal["series", "bool", "period", "number", "value"]
"""``series``: a numeric bar series. ``bool``: a condition series. ``period``:
a whole-number constant. ``number``: a decimal constant. ``value``: any
number (constant, series or point-in-time value)."""

Arrays = list[np.ndarray]
Compute = Callable[[pd.DataFrame, Arrays, tuple[float, ...]], dict[str, np.ndarray]]

MAX_PERIOD = 5000


@dataclass(frozen=True)
class Param:
    name: str
    kind: ParamKind
    default: float | None = None
    lo: float = 1
    hi: float = MAX_PERIOD


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    kind: Literal["indicator", "primitive"]
    params: tuple[Param, ...]
    compute: Compute
    lookback: Callable[..., int | None]
    """Own lookback from the constant arguments, in order."""
    outputs: tuple[str, ...] = ("value",)
    default_output: str | None = "value"
    variadic: bool = False
    """min/max: the single ``value`` parameter repeats (two or more)."""
    needs_benchmark: bool = False
    doc: str = ""
    returns: Literal["number"] = "number"
    registry_key: str | None = field(default=None)

    @property
    def const_params(self) -> tuple[Param, ...]:
        return tuple(p for p in self.params if p.kind in ("period", "number"))


# --- primitives -------------------------------------------------------------


def _s(x: np.ndarray) -> pd.Series:
    return pd.Series(x, dtype=float)


def _keep_missing(out: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.asarray(out, dtype=float).copy()
    out[np.isnan(x)] = np.nan
    return out


def _finite(out: np.ndarray) -> np.ndarray:
    out = np.asarray(out, dtype=float)
    out[~np.isfinite(out)] = np.nan
    return out


def shift(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if n < len(x):
        out[n:] = x[: len(x) - n]
    return out


def _sma(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    return {"value": _s(a[0]).rolling(int(c[0]), min_periods=int(c[0])).mean().to_numpy()}


def _ema(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    n = int(c[0])
    out = _s(a[0]).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()
    return {"value": _keep_missing(out, a[0])}


def _highest(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    return {"value": _s(a[0]).rolling(int(c[0]), min_periods=int(c[0])).max().to_numpy()}


def _lowest(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    return {"value": _s(a[0]).rolling(int(c[0]), min_periods=int(c[0])).min().to_numpy()}


def _sum(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    return {"value": _s(a[0]).rolling(int(c[0]), min_periods=int(c[0])).sum().to_numpy()}


def _change(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    return {"value": a[0] - shift(a[0], int(c[0]))}


def _pct_change(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    prev = shift(a[0], int(c[0]))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"value": _finite(100 * (a[0] / prev - 1))}


def _abs(_f, a: Arrays, _c) -> dict[str, np.ndarray]:
    return {"value": np.abs(a[0])}


def _min(_f, a: Arrays, _c) -> dict[str, np.ndarray]:
    return {"value": np.minimum.reduce(a)}


def _max(_f, a: Arrays, _c) -> dict[str, np.ndarray]:
    return {"value": np.maximum.reduce(a)}


def _count_true(_f, a: Arrays, c) -> dict[str, np.ndarray]:
    n = int(c[0])
    return {"value": _s(a[0]).rolling(n, min_periods=n).sum().to_numpy()}


def bars_since_values(b: np.ndarray) -> np.ndarray:
    """Bars since ``b`` was last true (0 when true now).

    Missing when it was never true in the history held, or when a bar since
    its last true one is unknown (it might have been true there)."""
    idx = np.arange(len(b))
    last_true = np.maximum.accumulate(np.where(b == 1.0, idx, -1)) if len(b) else idx
    last_unknown = np.maximum.accumulate(np.where(np.isnan(b), idx, -1)) if len(b) else idx
    out = (idx - last_true).astype(float)
    out[(last_true < 0) | (last_unknown > last_true)] = np.nan
    return out


def _bars_since(_f, a: Arrays, _c) -> dict[str, np.ndarray]:
    return {"value": bars_since_values(a[0])}


def _rs(f: pd.DataFrame, _a: Arrays, c) -> dict[str, np.ndarray]:
    n = int(c[0])
    close = f["close"].to_numpy(dtype=float)
    bench = f["bench"].to_numpy(dtype=float) if "bench" in f else np.full(len(f), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (close / shift(close, n)) / (bench / shift(bench, n))
        return {"value": _finite(100 * (ratio - 1))}


_SERIES = Param("series", "series")
_COND = Param("condition", "bool")


def _period(name: str = "n", default: float | None = None) -> Param:
    return Param(name, "period", default)


PRIMITIVES: tuple[FunctionSpec, ...] = (
    FunctionSpec("sma", "primitive", (_SERIES, _period()), _sma, lambda n: int(n) - 1,
                 doc="simple moving average of a series over n bars"),
    FunctionSpec("ema", "primitive", (_SERIES, _period()), _ema, lambda n: 5 * (int(n) + 1),
                 doc="exponential moving average (span n, the registry's EMA)"),
    FunctionSpec("highest", "primitive", (_SERIES, _period()), _highest, lambda n: int(n) - 1,
                 doc="highest value over the last n bars, this one included"),
    FunctionSpec("lowest", "primitive", (_SERIES, _period()), _lowest, lambda n: int(n) - 1,
                 doc="lowest value over the last n bars, this one included"),
    FunctionSpec("sum", "primitive", (_SERIES, _period()), _sum, lambda n: int(n) - 1,
                 doc="sum over the last n bars"),
    FunctionSpec("change", "primitive", (_SERIES, _period("n", 1)), _change, lambda n: int(n),
                 doc="value minus the value n bars ago (n defaults to 1)"),
    FunctionSpec("pct_change", "primitive", (_SERIES, _period("n", 1)), _pct_change,
                 lambda n: int(n), doc="percent change over n bars (n defaults to 1)"),
    FunctionSpec("abs", "primitive", (Param("x", "value"),), _abs, lambda: 0,
                 doc="absolute value"),
    FunctionSpec("min", "primitive", (Param("x", "value"),), _min, lambda: 0, variadic=True,
                 doc="smallest of two or more values, bar by bar"),
    FunctionSpec("max", "primitive", (Param("x", "value"),), _max, lambda: 0, variadic=True,
                 doc="largest of two or more values, bar by bar"),
    FunctionSpec("count_true", "primitive", (_COND, _period()), _count_true,
                 lambda n: int(n) - 1, doc="how many of the last n bars the condition held"),
    FunctionSpec("bars_since", "primitive", (_COND,), _bars_since, lambda: None,
                 doc="bars since the condition last held (0 when it holds now)"),
    FunctionSpec("rs", "primitive", (_period(),), _rs, lambda n: int(n), needs_benchmark=True,
                 doc="relative strength: percent by which the symbol's n-bar return beat its "
                     "venue's index (^GSPC for US listings, ^NSEI for Indian ones)"),
)  # fmt: skip


# --- registry indicators ----------------------------------------------------

DEFAULT_OUTPUTS: dict[str, str | None] = {
    "macd": "macd",
    "adx": "adx",
    "stoch": "k",
    "supertrend": "line",
    "bb": None,
    "donchian": None,
    "keltner": None,
    # A3.4
    "psar": "sar",
    "pivots": "pp",
    "stochrsi": "k",
    "tsi": "tsi",
    "ppo": "ppo",
    "ichimoku": None,
    "aroon": None,
    "vortex": None,
    "elder": None,
}

_OHLCV = ["open", "high", "low", "close", "volume"]


def _indicator_compute(spec: engine.Spec) -> Compute:
    def run(f: pd.DataFrame, _a: Arrays, c: tuple[float, ...]) -> dict[str, np.ndarray]:
        args = tuple(
            int(v) if is_int else float(v) for v, is_int in zip(c, _ints(spec), strict=True)
        )
        cols = [*_OHLCV, "bench"] if spec.needs_benchmark and "bench" in f else _OHLCV
        out = spec.compute(f[cols], *args)
        return {k: np.asarray(v, dtype=float) for k, v in out.items()}

    return run


def _ints(spec: engine.Spec) -> tuple[bool, ...]:
    return spec.integer or tuple(True for _ in spec.params)


def _indicator_lookback(spec: engine.Spec) -> Callable[..., int | None]:
    def lookback(*c: float) -> int | None:
        if spec.anchored == "start":
            return None  # cumulative: its level depends on the first bar held
        args = tuple(int(v) if i else float(v) for v, i in zip(c, _ints(spec), strict=True))
        return int(spec.lookback(*args))

    return lookback


def _indicator(spec: engine.Spec) -> FunctionSpec:
    # A3.4: each parameter's bounds are the registry's (``engine.Param``).
    params = tuple(
        Param(p.name, "period" if p.integer else "number", float(p.default), p.lo, p.hi)
        for p in spec.parameters
    )
    multi = len(spec.outputs) > 1
    return FunctionSpec(
        spec.key,
        "indicator",
        params,
        _indicator_compute(spec),
        _indicator_lookback(spec),
        outputs=spec.outputs,
        default_output=DEFAULT_OUTPUTS.get(spec.key) if multi else spec.outputs[0],
        doc=spec.label,
        needs_benchmark=spec.needs_benchmark,
        registry_key=spec.key,
    )


FUNCTIONS: dict[str, FunctionSpec] = {f.name: f for f in PRIMITIVES}
for _spec in engine.REGISTRY.values():
    if _spec.key not in FUNCTIONS:  # sma / ema are the primitives on close
        FUNCTIONS[_spec.key] = _indicator(_spec)


def validate_constant(fn: FunctionSpec, param: Param, value: float) -> str | None:
    """An error message when ``value`` is out of bounds for ``param``."""
    if param.kind == "period":
        hi = int(param.hi)
        if value != int(value) or not param.lo <= value <= hi:
            return f"{fn.name} {param.name} must be a whole number from {int(param.lo)} to {hi}"
    elif param.kind == "number" and not param.lo < value <= param.hi:
        return f"{fn.name} {param.name} must be above {param.lo:g} and at most {param.hi:g}"
    return None


__all__ = [
    "DEFAULT_OUTPUTS",
    "FUNCTIONS",
    "MAX_PERIOD",
    "PRIMITIVES",
    "FunctionSpec",
    "Param",
    "bars_since_values",
    "shift",
    "validate_constant",
]
