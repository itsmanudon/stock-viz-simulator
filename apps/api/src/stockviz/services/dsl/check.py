"""Type checker for the Rule DSL (A2.1). Runs before anything is evaluated.

Every expression has a **value** (``number`` or ``boolean``) and a **kind**:

- ``const``: a number written in the rule;
- ``series``: one value per bar (price, indicator, comparison);
- ``pit``: a point-in-time value as known on each bar's date
  (``fundamental.*``, ``news.*``). It mixes freely with series in arithmetic
  and comparisons, and anything built from it stays ``pit``. It has no bar
  history in a rule: no ``[n]`` offset, no windowed function, no crossing,
  and no timeframe prefix.

Timeframes: names inside ``weekly.`` / ``monthly.`` read resampled bars; the
prefix aligns the result back to the daily bar (the last closed period at
or before it). Prefixes do not nest, and fundamentals, news and delivery
data exist on the daily timeframe only. So a mix of daily and weekly values
can only come from an explicit prefix.

A rule must be a condition (``boolean``). Errors are ``RuleError("type",
...)`` with the line and column of the offending part.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

from stockviz.services.dsl import ast
from stockviz.services.dsl.bindings import (
    AVWAP_OUTPUTS,
    DELIVERY_SERIES,
    DRAWING_OUTPUTS,
    FUNDAMENTAL_METRICS,
    INDEX_SERIES,
    NEWS_FUNCTIONS,
    NEWS_MAX_DAYS,
    NEWS_SENTIMENTS,
    PRICE_SERIES,
    SERIES,
)
from stockviz.services.dsl.functions import FUNCTIONS, FunctionSpec, Param, validate_constant
from stockviz.services.dsl.parser import RuleError

Value = Literal["number", "boolean"]
Kind = Literal["const", "series", "pit"]
_KIND_ORDER = {"const": 0, "series": 1, "pit": 2}


@dataclass(frozen=True)
class Type:
    value: Value
    kind: Kind

    def __str__(self) -> str:
        names = {"const": "constant", "series": "series", "pit": "point-in-time value"}
        return f"{self.value} {names[self.kind]}"


def _join(*kinds: Kind) -> Kind:
    return max(kinds, key=lambda k: _KIND_ORDER[k])


def _err(node: ast.Node, message: str) -> RuleError:
    line, column = node.pos or (None, None)
    return RuleError("type", message, line, column)


def _suggest(word: str, choices) -> str:
    close = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.6)
    return f"; did you mean {close[0]}?" if close else ""


def bind_call(
    node: ast.Call | ast.News, params: tuple[Param, ...], fname: str, *, variadic: bool = False
) -> tuple[ast.Node | None, ...]:
    """Positional and keyword arguments -> one slot per parameter (None if
    left out). Variadic functions take positional arguments only."""
    if variadic:
        if node.kwargs:
            raise _err(node, f"{fname} takes values only, no keyword arguments")
        return tuple(node.args)
    if len(node.args) > len(params):
        raise _err(node, f"{fname} takes at most {len(params)} argument(s), got {len(node.args)}")
    slots: list[ast.Node | None] = [*node.args, *([None] * (len(params) - len(node.args)))]
    names = [p.name for p in params]
    for key, value in node.kwargs:
        if key not in names:
            raise _err(value, f"{fname} has no parameter {key!r} (it takes {', '.join(names)})")
        i = names.index(key)
        if slots[i] is not None:
            raise _err(value, f"{fname} got {key!r} twice")
        slots[i] = value
    return tuple(slots)


class _Checker:
    def check(self, node: ast.Node, tf: str) -> Type:
        method = getattr(self, f"_{type(node).__name__.lower()}")
        return method(node, tf)

    # --- leaves -------------------------------------------------------------

    def _num(self, node: ast.Num, tf: str) -> Type:
        return Type("number", "const")

    def _str(self, node: ast.Str, tf: str) -> Type:
        raise _err(node, "a string is allowed only as a keyword value")

    def _name(self, node: ast.Name, tf: str) -> Type:
        if node.name in PRICE_SERIES or node.name in INDEX_SERIES:
            return Type("number", "series")
        if node.name in DELIVERY_SERIES:
            if tf != "daily":
                raise _err(node, f"{node.name} is daily data and has no {tf} form")
            return Type("number", "series")
        if node.name in FUNCTIONS:
            raise _err(node, f"{node.name} is a function; write {node.name}(...)")
        if node.name in ("drawing", "avwap"):
            raise _err(node, f'{node.name} names one of your drawings: write {node.name}("label")')
        if node.name in FUNDAMENTAL_METRICS:
            raise _err(node, f"write fundamental.{node.name}")
        raise _err(node, f"unknown series {node.name!r}{_suggest(node.name, SERIES)}")

    def _fundamental(self, node: ast.Fundamental, tf: str) -> Type:
        if node.metric not in FUNDAMENTAL_METRICS:
            raise _err(
                node,
                f"unknown fundamental metric {node.metric!r}"
                f"{_suggest(node.metric, FUNDAMENTAL_METRICS)}",
            )
        if tf != "daily":
            raise _err(node, "fundamentals are known by date and have no weekly or monthly form")
        return Type("number", "pit")

    def _news(self, node: ast.News, tf: str) -> Type:
        if node.name not in NEWS_FUNCTIONS:
            raise _err(node, f"unknown news function {node.name!r}; news has count(days, ...)")
        if tf != "daily":
            raise _err(node, "news counts are daily only")
        params = (
            Param("days", "period"),
            Param("sentiment", "value"),
            Param("event_type", "value"),
        )
        days, sentiment, event_type = bind_call(node, params, "news.count")
        if days is None:
            raise _err(node, "news.count needs the number of days, e.g. news.count(7)")
        if not isinstance(days, ast.Num) or days.value != int(days.value):
            raise _err(days, "news.count days must be a whole number")
        if not 1 <= days.value <= NEWS_MAX_DAYS:
            raise _err(days, f"news.count days must be from 1 to {NEWS_MAX_DAYS}")
        if sentiment is not None and (
            not isinstance(sentiment, ast.Str) or sentiment.value not in NEWS_SENTIMENTS
        ):
            raise _err(sentiment, f"sentiment must be one of {', '.join(NEWS_SENTIMENTS)}")
        if event_type is not None and (
            not isinstance(event_type, ast.Str) or not 0 < len(event_type.value) <= 128
        ):
            raise _err(event_type, 'event_type must be a name in quotes, e.g. "earnings"')
        return Type("number", "pit")

    def _ref(self, node: ast.Ref, tf: str) -> Type:
        """A3.3: the owner's drawing or anchored VWAP, one value per daily bar."""
        if tf != "daily":
            raise _err(node, f"{node.kind}() reads a drawing on daily bars and has no {tf} form")
        if node.kind == "drawing":
            if node.output is None:
                raise _err(
                    node,
                    f'drawing() needs an output: drawing("{node.label}").price for a line, '
                    ".top or .bottom for a rectangle",
                )
            if node.output not in DRAWING_OUTPUTS:
                raise _err(
                    node,
                    f"drawing() has no output {node.output!r} (it has {', '.join(DRAWING_OUTPUTS)})",
                )
        elif node.output is not None and node.output not in AVWAP_OUTPUTS:
            raise _err(
                node, f"avwap() has no output {node.output!r} (it has {', '.join(AVWAP_OUTPUTS)})"
            )
        return Type("number", "series")

    # --- functions ----------------------------------------------------------

    def _call(self, node: ast.Call, tf: str) -> Type:
        fn = FUNCTIONS.get(node.name)
        if fn is None and node.name in ("drawing", "avwap"):
            raise _err(
                node,
                f'{node.name}() takes a drawing\'s label in quotes, e.g. {node.name}("support")',
            )
        if fn is None:
            raise _err(node, f"unknown function {node.name!r}{_suggest(node.name, FUNCTIONS)}")
        self._check_output(node, fn)
        slots = bind_call(node, fn.params, fn.name, variadic=fn.variadic)
        if fn.variadic and len(slots) < 2:
            raise _err(node, f"{fn.name} needs two or more values")
        kinds: list[Kind] = []
        params = [fn.params[0]] * len(slots) if fn.variadic else list(fn.params)
        for param, arg in zip(params, slots, strict=True):
            if arg is None:
                if param.default is None:
                    raise _err(node, f"{fn.name} needs {param.name}")
                continue
            kinds.append(self._check_arg(fn, param, arg, tf))
        if any(p.kind in ("series", "bool") for p in params) or fn.kind == "indicator":
            return Type("number", "series")
        if fn.needs_benchmark:
            return Type("number", "series")
        return Type("number", _join(*kinds) if kinds else "series")

    def _check_output(self, node: ast.Call, fn: FunctionSpec) -> None:
        if node.output is None:
            if fn.default_output is None:
                raise _err(
                    node,
                    f"{fn.name} has outputs {', '.join(fn.outputs)}; pick one, "
                    f"e.g. {fn.name}().{fn.outputs[0]}",
                )
            return
        if len(fn.outputs) == 1:
            raise _err(node, f"{fn.name} has one output; drop '.{node.output}'")
        if node.output not in fn.outputs:
            raise _err(
                node,
                f"{fn.name} has no output {node.output!r} (it has {', '.join(fn.outputs)})",
            )

    def _check_arg(self, fn: FunctionSpec, param: Param, arg: ast.Node, tf: str) -> Kind:
        if param.kind in ("period", "number"):
            value = _constant(arg)
            if value is None:
                raise _err(arg, f"{fn.name} {param.name} must be a number written in the rule")
            message = validate_constant(fn, param, value)
            if message:
                raise _err(arg, message)
            return "const"
        t = self.check(arg, tf)
        if param.kind == "series":
            if t.value != "number":
                raise _err(arg, f"{fn.name} needs a number series, got a {t.value}")
            if t.kind == "const":
                raise _err(arg, f"{fn.name} needs a series, not a constant")
            if t.kind == "pit":
                raise _err(arg, _PIT_HISTORY)
        elif param.kind == "bool":
            if t.value != "boolean":
                raise _err(arg, f"{fn.name} needs a condition, got a {t.value}")
            if t.kind == "pit":
                raise _err(arg, _PIT_HISTORY)
        elif t.value != "number":  # value
            raise _err(arg, f"{fn.name} needs a number, got a {t.value}")
        return t.kind

    # --- structure ----------------------------------------------------------

    def _offset(self, node: ast.Offset, tf: str) -> Type:
        t = self.check(node.expr, tf)
        if node.bars < 1:
            raise _err(node, "an offset must be at least [1]")
        if node.bars > 5000:
            raise _err(node, "an offset must be at most [5000]")
        if t.kind == "const":
            raise _err(node, "a constant has no earlier bars")
        if t.kind == "pit":
            raise _err(node, _PIT_HISTORY)
        return t

    def _timeframe(self, node: ast.Timeframe, tf: str) -> Type:
        if tf != "daily":
            raise _err(node, "timeframe prefixes do not nest")
        t = self.check(node.expr, node.timeframe)
        if t.kind == "const":
            raise _err(node, f"{node.timeframe}. needs a series")
        return t

    def _neg(self, node: ast.Neg, tf: str) -> Type:
        t = self.check(node.expr, tf)
        if t.value != "number":
            raise _err(node, "'-' needs a number")
        return t

    def _binop(self, node: ast.BinOp, tf: str) -> Type:
        left, right = self.check(node.left, tf), self.check(node.right, tf)
        for side, t in ((node.left, left), (node.right, right)):
            if t.value != "number":
                raise _err(side, f"'{node.op}' needs numbers, got a condition")
        return Type("number", _join(left.kind, right.kind))

    def _compare(self, node: ast.Compare, tf: str) -> Type:
        left, right = self.check(node.left, tf), self.check(node.right, tf)
        for side, t in ((node.left, left), (node.right, right)):
            if t.value != "number":
                raise _err(side, f"'{node.op}' compares numbers, got a condition")
        return Type("boolean", _join(left.kind, right.kind))

    def _cross(self, node: ast.Cross, tf: str) -> Type:
        left, right = self.check(node.left, tf), self.check(node.right, tf)
        for side, t in ((node.left, left), (node.right, right)):
            if t.value != "number":
                raise _err(side, f"{node.op} compares numbers, got a condition")
            if t.kind == "pit":
                raise _err(side, _PIT_HISTORY)
        if left.kind == right.kind == "const":
            raise _err(node, f"{node.op} needs at least one series")
        return Type("boolean", "series")

    def _not(self, node: ast.Not, tf: str) -> Type:
        t = self.check(node.expr, tf)
        if t.value != "boolean":
            raise _err(node, "not needs a condition")
        return t

    def _logic(self, node: ast.And | ast.Or, tf: str, word: str) -> Type:
        kinds: list[Kind] = []
        for operand in node.operands:
            t = self.check(operand, tf)
            if t.value != "boolean":
                raise _err(operand, f"{word} joins conditions, got a number")
            kinds.append(t.kind)
        return Type("boolean", _join(*kinds))

    def _and(self, node: ast.And, tf: str) -> Type:
        return self._logic(node, tf, "and")

    def _or(self, node: ast.Or, tf: str) -> Type:
        return self._logic(node, tf, "or")


_PIT_HISTORY = (
    "fundamental and news values are point-in-time and have no bar history in a rule: "
    "no [n], windowed function, crossing or timeframe prefix"
)


def _constant(node: ast.Node) -> float | None:
    return node.value if isinstance(node, ast.Num) else None


def check(node: ast.Node, *, require_condition: bool = True) -> Type:
    """The type of ``node``; raises ``RuleError("type", ...)``."""
    t = _Checker().check(node, "daily")
    if require_condition and t.value != "boolean":
        raise _err(node, "a rule must be a condition (true or false), not a number")
    return t


__all__ = ["Type", "bind_call", "check"]
