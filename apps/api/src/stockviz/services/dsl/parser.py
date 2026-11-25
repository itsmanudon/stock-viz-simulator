"""Parse rule text into the syntax tree (A2.1), with Lark (MIT, LALR).

``parse(text)`` returns the tree as written. Errors are :class:`RuleError`
with a line, a column and a short message a person can act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lark import Lark, Token, Transformer, Tree, v_args
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken

from stockviz.services.dsl import ast

GRAMMAR_PATH = Path(__file__).with_name("grammar.lark")
MAX_RULE_LENGTH = 4000

_FRIENDLY = {
    "NAME": "a name",
    "NUMBER": "a number",
    "INT": "a whole number",
    "STRING": "a string",
    "LPAR": "'('",
    "RPAR": "')'",
    "LSQB": "'['",
    "RSQB": "']'",
    "COMMA": "','",
    "DOT": "'.'",
    "COMP_OP": "a comparison",
    "CROSS_OP": "crosses_above or crosses_below",
    "ADD_OP": "'+' or '-'",
    "MUL_OP": "'*' or '/'",
    "MINUS": "'-'",
    "TIMEFRAME": "weekly or monthly",
    "_AND": "and",
    "_OR": "or",
    "_NOT": "not",
    "_FUNDAMENTAL": "fundamental",
    "_NEWS": "news",
    "EQUAL": "'='",
    "$END": "the end of the rule",
}


@dataclass
class RuleError(Exception):
    """A syntax or type error, with where it happened (line and column from 1)."""

    kind: str  # "syntax" | "type"
    message: str
    line: int | None = None
    column: int | None = None
    text: str | None = None

    def __str__(self) -> str:
        where = f" at line {self.line}, column {self.column}" if self.line else ""
        return f"{self.kind} error{where}: {self.message}"

    def pretty(self) -> str:
        """The message, then the offending line with a caret under the column."""
        out = str(self)
        if self.text is not None and self.line is not None and self.column is not None:
            lines = self.text.splitlines() or [""]
            if 1 <= self.line <= len(lines):
                out += f"\n  {lines[self.line - 1]}\n  {' ' * (self.column - 1)}^"
        return out


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(
        GRAMMAR_PATH.read_text(),
        parser="lalr",
        propagate_positions=True,
        maybe_placeholders=False,
    )


def _pos(meta) -> ast.Pos | None:
    line = getattr(meta, "line", None)
    column = getattr(meta, "column", None)
    return (line, column) if line is not None and column is not None else None


def _tpos(token: Token) -> ast.Pos | None:
    return (token.line, token.column) if token.line is not None else None  # pyright: ignore[reportReturnType]


def _flatten(cls: type[ast.And] | type[ast.Or], items: list[ast.Node]) -> tuple[ast.Node, ...]:
    out: list[ast.Node] = []
    for item in items:
        out.extend(item.operands if isinstance(item, cls) else (item,))
    return tuple(out)


class _Build(Transformer):
    """Lark tree -> ``ast`` nodes."""

    @v_args(meta=True)
    def or_(self, meta, items):
        return ast.Or(_flatten(ast.Or, items), pos=_pos(meta))

    @v_args(meta=True)
    def and_(self, meta, items):
        return ast.And(_flatten(ast.And, items), pos=_pos(meta))

    @v_args(meta=True)
    def not_(self, meta, items):
        return ast.Not(items[0], pos=_pos(meta))

    @v_args(meta=True)
    def compare(self, meta, items):
        left, op, right = items
        symbol = "=" if str(op) == "==" else str(op)
        return ast.Compare(symbol, left, right, pos=_pos(meta))

    @v_args(meta=True)
    def cross(self, meta, items):
        left, op, right = items
        return ast.Cross(str(op), left, right, pos=_pos(meta))

    @v_args(meta=True)
    def binop(self, meta, items):
        left, op, right = items
        return ast.BinOp(str(op), left, right, pos=_pos(meta))

    @v_args(meta=True)
    def neg(self, meta, items):
        return ast.Neg(items[0], pos=_pos(meta))

    @v_args(meta=True)
    def timeframe(self, meta, items):
        tf, expr = items
        return ast.Timeframe(str(tf), expr, pos=_pos(meta))

    @v_args(meta=True)
    def offset(self, meta, items):
        expr, n = items
        return ast.Offset(expr, int(str(n)), pos=_pos(meta))

    @v_args(meta=True)
    def output(self, meta, items):
        expr, name = items
        if isinstance(expr, ast.Name) and expr.name in ("weekly", "monthly"):
            raise RuleError("syntax", "timeframe prefixes do not nest", *(expr.pos or (None, None)))
        if not isinstance(expr, ast.Call) or expr.output is not None:
            raise RuleError(
                "syntax",
                f"'.{name}' picks an indicator output and must follow a call, e.g. macd().{name}",
                *(_tpos(name) or (None, None)),
            )
        return ast.Call(expr.name, expr.args, expr.kwargs, str(name), pos=expr.pos)

    def number(self, items):
        token = items[0]
        return ast.Num(float(str(token)), pos=_tpos(token))

    def name(self, items):
        token = items[0]
        return ast.Name(str(token), pos=_tpos(token))

    def call(self, items):
        token = items[0]
        args, kwargs = items[1] if len(items) > 1 else ((), ())
        return ast.Call(str(token), args, kwargs, pos=_tpos(token))

    @v_args(meta=True)
    def fundamental(self, meta, items):
        return ast.Fundamental(str(items[0]), pos=_pos(meta))

    @v_args(meta=True)
    def news(self, meta, items):
        token = items[0]
        args, kwargs = items[1] if len(items) > 1 else ((), ())
        return ast.News(str(token), args, kwargs, pos=_pos(meta))

    def args(self, items):
        args: list[ast.Node] = []
        kwargs: list[tuple[str, ast.Node]] = []
        for item in items:
            if isinstance(item, tuple):
                kwargs.append(item)
            else:
                if kwargs:
                    raise RuleError(
                        "syntax",
                        "a positional argument cannot follow a keyword argument",
                        *(item.pos or (None, None)),
                    )
                args.append(item)
        return tuple(args), tuple(kwargs)

    def kwarg(self, items):
        key, value = items
        if isinstance(value, Token):  # STRING
            value = ast.Str(str(value)[1:-1], pos=_tpos(value))
        return (str(key), value)


def _describe_expected(expected: set[str]) -> str:
    names = sorted({_FRIENDLY.get(e, e.lower()) for e in expected if not e.startswith("__")})
    if not names:
        return ""
    if len(names) > 6:
        return ""
    return "; expected " + ", ".join(names)


def _syntax_error(text: str, exc: UnexpectedInput) -> RuleError:
    line, column = exc.line, exc.column
    if isinstance(exc, UnexpectedCharacters):
        char = text[exc.pos_in_stream] if exc.pos_in_stream is not None else "?"
        if char.isupper():
            message = "names are lowercase (close, sma, fundamental.pe)"
        elif char == '"':
            message = 'a string is allowed only as a keyword value, e.g. sentiment="negative"'
        else:
            message = f"unexpected character {char!r}"
    elif isinstance(exc, UnexpectedToken):
        token = exc.token
        if token.type == "$END":
            message = "the rule ends too early" + _describe_expected(exc.expected)
            lines = text.splitlines() or [""]
            line, column = len(lines), len(lines[-1]) + 1
        elif token.type == "STRING":
            message = 'a string is allowed only as a keyword value, e.g. sentiment="negative"'
        elif token.type in ("COMP_OP", "CROSS_OP") and "_AND" in exc.expected:
            message = "comparisons cannot be chained; join them with and"
        else:
            message = f"unexpected {str(token)!r}" + _describe_expected(exc.expected)
    elif isinstance(exc, UnexpectedEOF):
        message = "the rule ends too early"
    else:  # pragma: no cover
        message = str(exc).splitlines()[0]
    if line is None or line < 1:
        lines = text.splitlines() or [""]
        line, column = len(lines), len(lines[-1]) + 1
    return RuleError("syntax", message, line, column, text)


def parse(text: str) -> ast.Node:
    """Rule text -> its syntax tree as written. Raises :class:`RuleError`."""
    if not text.strip():
        raise RuleError("syntax", "the rule is empty", 1, 1, text)
    if len(text) > MAX_RULE_LENGTH:
        raise RuleError(
            "syntax", f"the rule is longer than {MAX_RULE_LENGTH} characters", 1, 1, text
        )
    try:
        tree = _parser().parse(text)
    except UnexpectedInput as exc:
        raise _syntax_error(text, exc) from None
    try:
        node = _Build().transform(tree) if isinstance(tree, Tree) else tree
    except RuleError as exc:
        exc.text = text
        raise
    except Exception as exc:  # lark wraps transformer errors
        inner = getattr(exc, "orig_exc", None)
        if isinstance(inner, RuleError):
            inner.text = text
            raise inner from None
        raise
    if isinstance(node, Token):  # a lone NUMBER/NAME is inlined by '?' rules
        raise RuleError("syntax", "unexpected input", 1, 1, text)  # pragma: no cover
    return node


__all__ = ["GRAMMAR_PATH", "RuleError", "parse"]
