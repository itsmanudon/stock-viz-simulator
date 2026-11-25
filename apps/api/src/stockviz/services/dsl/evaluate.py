"""Compile and evaluate rules (A2.1): one evaluator, run two ways.

- :func:`vector` evaluates a rule over a symbol's whole daily history at once
  (scans, and later backtests).
- :func:`point` evaluates it at bar ``t``: the *same code* on the data cut at
  ``t`` (:meth:`SymbolData.cut`), so it can only see what was known then
  (alerts, replay). ``tests/test_dsl_conformance.py`` proves
  ``point(t) == vector[t]`` for every bar of a 10-year history and every
  rule in its corpus, which also proves a vector value never depends on a
  later bar.

**Three-valued logic.** Values are float arrays; a condition is 1.0 (true),
0.0 (false) or NaN (unknown). Any comparison with a missing input is
unknown. ``and`` / ``or`` / ``not`` are Kleene's: false and unknown is
false, true or unknown is true, not unknown is unknown. At the boundary a
condition becomes a pandas nullable ``boolean`` Series (``pd.NA`` for
unknown), and a judged bar is ``met``, ``not_met`` or ``unknown`` with the
reasons: which binding was missing, or which function lacked history.
"""

# pyright: reportArgumentType=false, reportCallIssue=false, reportIndexIssue=false, reportAttributeAccessIssue=false

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from stockviz.services.bars.resample import MAX_SESSIONS_PER_PERIOD
from stockviz.services.dsl import ast
from stockviz.services.dsl.bindings import DELIVERY_SERIES, INTERVAL_BY_TIMEFRAME
from stockviz.services.dsl.canonical import canonicalize, rule_hash
from stockviz.services.dsl.check import Type, check
from stockviz.services.dsl.data import Needs, SymbolData
from stockviz.services.dsl.functions import FUNCTIONS, FunctionSpec, shift
from stockviz.services.dsl.parser import RuleError, parse
from stockviz.services.dsl.printer import format_number, to_text

Status = Literal["met", "not_met", "unknown"]
NAN = float("nan")


# --- compile ----------------------------------------------------------------


@dataclass(frozen=True)
class CompiledRule:
    text: str
    tree: ast.Node
    canonical: ast.Node
    canonical_text: str
    hash: str
    type: Type
    lookback: int | None
    """Daily bars needed before the first bar judged; None: the whole history."""
    needs: Needs


def _params(fn: FunctionSpec, n: int):
    return [fn.params[0]] * n if fn.variadic else list(fn.params)


def lookback(node: ast.Node, tf: str = "daily") -> int | None:
    """Bars of ``tf`` needed before a value of ``node`` (canonical tree)."""
    match node:
        case ast.Call(name=name, args=args):
            fn = FUNCTIONS[name]
            consts = []
            inner: list[int | None] = [0]
            for param, arg in zip(_params(fn, len(args)), args, strict=True):
                if param.kind in ("period", "number"):
                    assert isinstance(arg, ast.Num)
                    consts.append(arg.value)
                else:
                    inner.append(lookback(arg, tf))
            own = fn.lookback(*consts)
            if own is None or any(i is None for i in inner):
                return None
            return own + max(i for i in inner if i is not None)
        case ast.Offset(expr=expr, bars=bars):
            sub = lookback(expr, tf)
            return None if sub is None else sub + bars
        case ast.Cross(left=left, right=right):
            subs = [lookback(left, tf), lookback(right, tf)]
            return None if None in subs else 1 + max(s for s in subs if s is not None)
        case ast.Timeframe(timeframe=timeframe, expr=expr):
            sub = lookback(expr, timeframe)
            per = MAX_SESSIONS_PER_PERIOD[INTERVAL_BY_TIMEFRAME[timeframe]]
            return None if sub is None else (sub + 2) * per
    subs = [lookback(c, tf) for c in node.children()]
    if None in subs:
        return None
    return max((s for s in subs if s is not None), default=0)


def needs(node: ast.Node) -> Needs:
    nodes = list(ast.walk(node))
    return Needs(
        benchmark=any(isinstance(n, ast.Call) and FUNCTIONS[n.name].needs_benchmark for n in nodes),
        fundamentals=any(isinstance(n, ast.Fundamental) for n in nodes),
        news=any(isinstance(n, ast.News) for n in nodes),
        delivery=any(isinstance(n, ast.Name) and n.name in DELIVERY_SERIES for n in nodes),
    )


def compile_rule(text: str, *, require_condition: bool = True) -> CompiledRule:
    """Parse, type-check and canonicalize. Raises :class:`RuleError`."""
    tree = parse(text)
    try:
        kind = check(tree, require_condition=require_condition)
    except RuleError as exc:
        exc.text = text
        raise
    canonical = canonicalize(tree)
    canonical_text = to_text(canonical)
    return CompiledRule(
        text, tree, canonical, canonical_text, rule_hash(canonical_text), kind,
        lookback(canonical), needs(canonical),
    )  # fmt: skip


def _compiled(rule: CompiledRule | str) -> CompiledRule:
    return rule if isinstance(rule, CompiledRule) else compile_rule(rule, require_condition=False)


# --- evaluation -------------------------------------------------------------


def _kleene_and(values: list[np.ndarray]) -> np.ndarray:
    stack = np.vstack(values)
    out = np.where(np.isnan(stack).any(axis=0), NAN, 1.0)
    out[(stack == 0.0).any(axis=0)] = 0.0
    return out


def _kleene_or(values: list[np.ndarray]) -> np.ndarray:
    stack = np.vstack(values)
    out = np.where(np.isnan(stack).any(axis=0), NAN, 0.0)
    out[(stack == 1.0).any(axis=0)] = 1.0
    return out


def _compare(op: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        result = {
            "<": a < b,
            "<=": a <= b,
            ">": a > b,
            ">=": a >= b,
            "=": a == b,
            "!=": a != b,
        }[op]
    return np.where(np.isnan(a) | np.isnan(b), NAN, result.astype(float))


def _arith(op: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[op]
    out = np.asarray(out, dtype=float)
    out[~np.isfinite(out)] = NAN
    return out


class Evaluation:
    """One rule on one symbol's data. Sub-expression values are cached by
    (node, timeframe), which :func:`explain` and the reasons read back."""

    def __init__(self, data: SymbolData, *, benchmark: bool = True):
        self.data = data
        daily = data.bars
        if benchmark and data.benchmark is not None:
            daily = daily.assign(
                bench=data.benchmark.reindex(daily.index, method="ffill", limit=5).to_numpy()
            )
        self.frames: dict[str, pd.DataFrame] = {"daily": daily}
        self.align: dict[str, np.ndarray] = {}
        self.cache: dict[tuple[ast.Node, str], np.ndarray] = {}
        self._indicators: dict[tuple, dict[str, np.ndarray]] = {}
        self._fundamentals = None

    def frame(self, tf: str) -> pd.DataFrame:
        if tf not in self.frames:
            from stockviz.services.dsl.timeframes import resample_frame

            resampled = resample_frame(
                self.frames["daily"], INTERVAL_BY_TIMEFRAME[tf], self.data.venue
            )
            self.frames[tf] = resampled.frame
            self.align[tf] = resampled.align
        return self.frames[tf]

    def fundamentals_table(self):
        if self._fundamentals is None and self.data.fundamentals is not None:
            daily = self.frames["daily"]
            self._fundamentals = self.data.fundamentals.table(
                daily.index.to_numpy(dtype="datetime64[D]"), daily["close"].to_numpy(dtype=float)
            )
        return self._fundamentals

    def value(self, node: ast.Node, tf: str = "daily") -> np.ndarray:
        key = (node, tf)
        hit = self.cache.get(key)
        if hit is None:
            hit = self._value(node, tf)
            self.cache[key] = hit
        return hit

    def _value(self, node: ast.Node, tf: str) -> np.ndarray:
        n = len(self.frame(tf))
        match node:
            case ast.Num(value=v):
                return np.full(n, v, dtype=float)
            case ast.Name(name=name):
                frame = self.frame(tf)
                if name not in frame:
                    return np.full(n, NAN)
                return frame[name].to_numpy(dtype=float)
            case ast.Fundamental(metric=metric):
                table = self.fundamentals_table()
                return table.values[metric] if table is not None else np.full(n, NAN)
            case ast.News():
                if self.data.news is None:
                    return np.full(n, NAN)
                days = int(node.args[0].value)  # type: ignore[attr-defined]
                kw = {k: v.value for k, v in node.kwargs}  # type: ignore[attr-defined]
                return self.data.news.count(
                    days,
                    self.data.cutoffs(),
                    sentiment=kw.get("sentiment"),
                    event_type=kw.get("event_type"),
                )
            case ast.Call():
                return self._call(node, tf)
            case ast.Offset(expr=expr, bars=bars):
                return shift(self.value(expr, tf), bars)
            case ast.Timeframe(timeframe=timeframe, expr=expr):
                inner = self.value(expr, timeframe)
                align = self.align[timeframe]
                return np.where(align >= 0, inner[np.maximum(align, 0)] if len(inner) else NAN, NAN)
            case ast.Neg(expr=expr):
                return -self.value(expr, tf)
            case ast.BinOp(op=op, left=left, right=right):
                return _arith(op, self.value(left, tf), self.value(right, tf))
            case ast.Compare(op=op, left=left, right=right):
                return _compare(op, self.value(left, tf), self.value(right, tf))
            case ast.Cross(op=op, left=left, right=right):
                a, b = self.value(left, tf), self.value(right, tf)
                now = _compare(">" if op == "crosses_above" else "<", a, b)
                before = _compare("<=" if op == "crosses_above" else ">=", shift(a, 1), shift(b, 1))
                return _kleene_and([now, before])
            case ast.Not(expr=expr):
                return 1.0 - self.value(expr, tf)
            case ast.And(operands=ops):
                return _kleene_and([self.value(o, tf) for o in ops])
            case ast.Or(operands=ops):
                return _kleene_or([self.value(o, tf) for o in ops])
        raise TypeError(f"cannot evaluate {node!r}")  # pragma: no cover

    def _call(self, node: ast.Call, tf: str) -> np.ndarray:
        fn = FUNCTIONS[node.name]
        consts: list[float] = []
        arrays: list[np.ndarray] = []
        for param, arg in zip(_params(fn, len(node.args)), node.args, strict=True):
            if param.kind in ("period", "number"):
                consts.append(arg.value)  # type: ignore[attr-defined]
            else:
                arrays.append(self.value(arg, tf))
        frame = self.frame(tf)
        if fn.kind == "indicator":
            key = (fn.name, tuple(consts), tf)
            outputs = self._indicators.get(key)
            if outputs is None:
                outputs = fn.compute(frame, arrays, tuple(consts))
                self._indicators[key] = outputs
            return outputs[node.output or fn.default_output or fn.outputs[0]]
        return np.asarray(fn.compute(frame, arrays, tuple(consts))["value"], dtype=float)

    # --- reasons ------------------------------------------------------------

    def index_in(self, tf: str, i: int) -> int:
        """Row of ``tf``'s frame aligned to daily row ``i`` (-1: none)."""
        if tf == "daily":
            return i
        self.frame(tf)
        return int(self.align[tf][i])

    def reasons(self, node: ast.Node, tf: str, i: int) -> list[str]:
        """Why ``node`` is unknown at row ``i`` of ``tf`` ([] if it is known)."""
        values = self.value(node, tf)
        if i < 0:
            return ["no bar"]
        if not np.isnan(values[i]):
            return []
        text = to_text(node)
        day = self.frame(tf).index[i].date()
        match node:
            case ast.Name(name=name):
                if name in DELIVERY_SERIES:
                    if not self.data.delivery_loaded:
                        return [f"{name}: no delivery data for {self.data.ticker} (eod_extras)"]
                    return [f"{name}: no delivery data on {day.isoformat()}"]
                return [f"{name}: no value on {day.isoformat()}"]
            case ast.Fundamental(metric=metric):
                table = self.fundamentals_table()
                if table is None:
                    return [f"{text}: no fundamentals loaded"]
                return [f"{text}: {table.reason(metric, i, day)}"]
            case ast.News():
                news = self.data.news
                return [f"{text}: {news.reason() if news else 'no news loaded'}"]
            case ast.Timeframe(timeframe=timeframe, expr=expr):
                j = self.index_in(timeframe, i)
                if j < 0:
                    return [f"{text}: no closed {timeframe} bar yet"]
                return self.reasons(expr, timeframe, j)
            case ast.Offset(expr=expr, bars=bars):
                if i - bars < 0:
                    return [f"{text}: not enough history ({i + 1} bars)"]
                return self.reasons(expr, tf, i - bars)
            case ast.Cross(left=left, right=right):
                found = self._child_reasons((left, right), tf, i)
                if not found and i >= 1:
                    found = self._child_reasons((left, right), tf, i - 1)
                return found or [f"{text}: needs a previous bar"]
            case ast.And(operands=ops) | ast.Or(operands=ops):
                return self._child_reasons(ops, tf, i)
            case ast.Call():
                return self._call_reasons(node, tf, i, text)
        found = self._child_reasons(node.children(), tf, i)
        if found:
            return found
        if isinstance(node, ast.BinOp) and node.op == "/":
            return [f"{text}: division by zero"]
        return [f"{text}: no value"]

    def _child_reasons(self, children, tf: str, i: int) -> list[str]:
        out: list[str] = []
        for child in children:
            for reason in self.reasons(child, tf, i):
                if reason not in out:
                    out.append(reason)
        return out

    def _call_reasons(self, node: ast.Call, tf: str, i: int, text: str) -> list[str]:
        fn = FUNCTIONS[node.name]
        series_args = [
            a
            for p, a in zip(_params(fn, len(node.args)), node.args, strict=True)
            if p.kind not in ("period", "number")
        ]
        found = self._child_reasons(series_args, tf, i)
        if found:
            return found
        if fn.needs_benchmark and (
            "bench" not in self.frame(tf) or np.isnan(self.frame(tf)["bench"].to_numpy()[i])
        ):
            name = self.data.benchmark_ticker or "the venue's index"
            return [f"{text}: no {name} close on this bar"]
        need = lookback(node, tf)
        # A missing input inside the window: report the latest one.
        if need:
            for arg in series_args:
                values = self.value(arg, tf)
                window = values[max(0, i - need) : i + 1]
                bad = np.flatnonzero(np.isnan(window))
                if len(bad):
                    reasons = self.reasons(arg, tf, max(0, i - need) + int(bad[-1]))
                    if reasons:
                        return reasons
        if need is None:
            return [f"{text}: no value in the history held"]
        if i < need:
            unit = "bars" if tf == "daily" else f"{tf} bars"
            return [f"{text}: not enough history (needs {need + 1} {unit}, has {i + 1})"]
        return [f"{text}: no value"]


# --- public API -------------------------------------------------------------


def _as_series(rule: CompiledRule, values: np.ndarray, index: pd.Index) -> pd.Series:
    if rule.type.value == "boolean":
        data = pd.array([pd.NA if np.isnan(v) else bool(v) for v in values], dtype="boolean")
        return pd.Series(data, index=index, dtype="boolean")
    return pd.Series(values, index=index, dtype=float)


def vector(rule: CompiledRule | str, data: SymbolData) -> pd.Series:
    """The rule on every daily bar: a nullable ``boolean`` Series for a
    condition (``pd.NA`` = unknown), float with NaN for a number."""
    compiled = _compiled(rule)
    ev = Evaluation(data, benchmark=compiled.needs.benchmark)
    return _as_series(compiled, ev.value(compiled.canonical), data.bars.index)


def _bar_index(data: SymbolData, t: date) -> int:
    ts = pd.Timestamp(t)
    if len(data.bars) == 0 or data.bars.index[-1] != ts:
        raise ValueError(f"{data.ticker} has no bar on {t.isoformat()}")
    return len(data.bars) - 1


def point(rule: CompiledRule | str, data: SymbolData, t: date) -> bool | float | None:
    """The rule at bar ``t``, from the data cut at ``t``: True / False / None
    (unknown) for a condition, a float or None for a number."""
    compiled = _compiled(rule)
    cut = data.cut(t)
    i = _bar_index(cut, t)
    value = Evaluation(cut, benchmark=compiled.needs.benchmark).value(compiled.canonical)[i]
    if np.isnan(value):
        return None
    return bool(value) if compiled.type.value == "boolean" else float(value)


@dataclass(frozen=True)
class Outcome:
    status: Status
    bar_date: date
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplainRow:
    text: str
    timeframe: str
    value: str


def _format(value: float, boolean: bool) -> str:
    if np.isnan(value):
        return "unknown"
    if boolean:
        return "true" if value == 1.0 else "false"
    return format_number(round(float(value), 6))


def _is_boolean(node: ast.Node) -> bool:
    return isinstance(node, (ast.Compare, ast.Cross, ast.Not, ast.And, ast.Or)) or (
        isinstance(node, ast.Timeframe) and _is_boolean(node.expr)
    )


def evaluate_at(
    rule: CompiledRule | str, data: SymbolData, t: date, *, explain: bool = False
) -> tuple[Outcome, list[ExplainRow]]:
    """Judge a condition at bar ``t`` (point mode) with its reasons, and
    optionally every sub-expression's value."""
    compiled = _compiled(rule)
    cut = data.cut(t)
    i = _bar_index(cut, t)
    ev = Evaluation(cut, benchmark=compiled.needs.benchmark)
    value = ev.value(compiled.canonical)[i]
    if np.isnan(value):
        outcome = Outcome("unknown", t, tuple(ev.reasons(compiled.canonical, "daily", i)))
    else:
        outcome = Outcome("met" if value == 1.0 else "not_met", t)
    rows: list[ExplainRow] = []
    if explain:
        rows = _explain(ev, compiled.canonical, "daily", i)
    return outcome, rows


def _explain(ev: Evaluation, node: ast.Node, tf: str, i: int) -> list[ExplainRow]:
    """Each sub-expression once, parents first. A function call is one row:
    its arguments are bar series, already listed elsewhere or not worth a row."""
    rows: list[ExplainRow] = []
    seen: set[tuple[str, str]] = set()

    def visit(n: ast.Node, tf: str, i: int) -> None:
        if isinstance(n, (ast.Num, ast.Str)):
            return
        values = ev.value(n, tf)
        shown = _format(values[i], _is_boolean(n)) if i >= 0 else "unknown"
        key = (to_text(n), tf if i >= 0 else "")
        if key not in seen:
            seen.add(key)
            rows.append(ExplainRow(key[0], tf, shown))
        if isinstance(n, ast.Timeframe):
            visit(n.expr, n.timeframe, ev.index_in(n.timeframe, i))
        elif isinstance(n, ast.Offset):
            return
        elif not isinstance(n, (ast.Call, ast.News)):
            for child in n.children():
                visit(child, tf, i)

    visit(node, tf, i)
    return rows


__all__ = [
    "CompiledRule",
    "Evaluation",
    "ExplainRow",
    "Outcome",
    "compile_rule",
    "evaluate_at",
    "lookback",
    "needs",
    "point",
    "vector",
]
