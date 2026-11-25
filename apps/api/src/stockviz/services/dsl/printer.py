"""Print a syntax tree back as rule text (A2.1).

Deterministic: one space around binary operators and after commas, none
inside brackets, parentheses only where precedence needs them. Numbers print
in their shortest form (``2`` for 2.0). For any tree the parser produced,
``parse(to_text(tree)) == tree``.
"""

from __future__ import annotations

from decimal import Decimal

from stockviz.services.dsl import ast

_OR, _AND, _NOT, _CMP, _SUM, _PRODUCT, _UNARY, _POSTFIX, _ATOM = range(1, 10)


def format_number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = repr(value)
    if "e" in text or "E" in text:  # the grammar has no exponent form
        text = format(Decimal(text), "f")
    return text


def _prec(node: ast.Node) -> int:
    match node:
        case ast.Or():
            return _OR
        case ast.And():
            return _AND
        case ast.Not():
            return _NOT
        case ast.Compare() | ast.Cross():
            return _CMP
        case ast.BinOp(op=op):
            return _SUM if op in "+-" else _PRODUCT
        case ast.Neg() | ast.Timeframe():
            return _UNARY
        case ast.Offset():
            return _POSTFIX
        case _:
            return _ATOM


def _wrap(node: ast.Node, minimum: int) -> str:
    text = to_text(node)
    return f"({text})" if _prec(node) < minimum else text


def _args(args: tuple[ast.Node, ...], kwargs: tuple[tuple[str, ast.Node], ...]) -> str:
    parts = [to_text(a) for a in args]
    parts += [f"{k}={to_text(v)}" for k, v in kwargs]
    return ", ".join(parts)


def to_text(node: ast.Node) -> str:
    match node:
        case ast.Num(value=value):
            return format_number(value)
        case ast.Str(value=value):
            return f'"{value}"'
        case ast.Name(name=name):
            return name
        case ast.Fundamental(metric=metric):
            return f"fundamental.{metric}"
        case ast.Call(name=name, args=args, kwargs=kwargs, output=output):
            text = f"{name}({_args(args, kwargs)})"
            return f"{text}.{output}" if output else text
        case ast.Ref(kind=kind, label=label, output=output):
            text = f'{kind}("{label}")'
            return f"{text}.{output}" if output else text
        case ast.News(name=name, args=args, kwargs=kwargs):
            return f"news.{name}({_args(args, kwargs)})"
        case ast.Offset(expr=expr, bars=bars):
            return f"{_wrap(expr, _POSTFIX)}[{bars}]"
        case ast.Timeframe(timeframe=tf, expr=expr):
            return f"{tf}.{_wrap(expr, _POSTFIX)}"
        case ast.Neg(expr=expr):
            return f"-{_wrap(expr, _UNARY)}"
        case ast.BinOp(op=op, left=left, right=right):
            p = _prec(node)
            return f"{_wrap(left, p)} {op} {_wrap(right, p + 1)}"
        case ast.Compare(op=op, left=left, right=right) | ast.Cross(op=op, left=left, right=right):
            return f"{_wrap(left, _SUM)} {op} {_wrap(right, _SUM)}"
        case ast.Not(expr=expr):
            return f"not {_wrap(expr, _NOT)}"
        case ast.And(operands=ops):
            return " and ".join(_wrap(o, _NOT) for o in ops)
        case ast.Or(operands=ops):
            return " or ".join(_wrap(o, _AND) for o in ops)
    raise TypeError(f"cannot print {node!r}")  # pragma: no cover


__all__ = ["format_number", "to_text"]
