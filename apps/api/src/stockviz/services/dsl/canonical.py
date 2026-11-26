"""Canonical form and hash of a rule (A2.1).

``canonicalize`` rewrites a checked tree into the one tree that names the
rule:

- every function argument by position, defaults written out
  (``rsi()`` -> ``rsi(14)``, ``bb(20, k=2)`` -> ``bb(20, 2)``);
- a default output dropped (``adx(14).adx`` -> ``adx(14)``);
- ``news.count`` keywords in name order;
- a drawing label (A3.3) trimmed and lowercased (labels match ignoring
  case), ``avwap("x").vwap`` written ``avwap("x")``;
- ``and`` / ``or`` flattened and their operands sorted by canonical text.
  Kleene ``and``/``or`` are commutative and associative, so this never
  changes a result. Nothing else is reordered: not comparisons (``a < b`` is
  not ``b > a`` in the text), and not ``+`` or ``*`` (floating-point sums
  depend on order).

The **hash** is the SHA-256 of the canonical text, so spacing, ``==`` for
``=``, keyword order and the order of an ``and`` do not change it.
"""

from __future__ import annotations

import hashlib

from stockviz.services.dsl import ast
from stockviz.services.dsl.check import bind_call
from stockviz.services.dsl.functions import FUNCTIONS
from stockviz.services.dsl.printer import to_text


def _sorted(cls: type[ast.And] | type[ast.Or], operands: tuple[ast.Node, ...]) -> tuple:
    flat: list[ast.Node] = []
    for o in operands:
        c = canonicalize(o)
        flat.extend(c.operands if isinstance(c, cls) else (c,))
    return tuple(sorted(flat, key=to_text))


def canonicalize(node: ast.Node) -> ast.Node:
    """The canonical tree of a type-checked ``node`` (positions kept)."""
    pos = node.pos
    match node:
        case ast.Call():
            fn = FUNCTIONS[node.name]
            slots = bind_call(node, fn.params, fn.name, variadic=fn.variadic)
            params = [fn.params[0]] * len(slots) if fn.variadic else fn.params
            args: list[ast.Node] = []
            for param, arg in zip(params, slots, strict=True):
                if arg is None:
                    assert param.default is not None
                    args.append(ast.Num(float(param.default)))
                else:
                    args.append(canonicalize(arg))
            output = None if node.output == fn.default_output else node.output
            return ast.Call(node.name, tuple(args), (), output, pos=pos)
        case ast.Ref():
            output = None if node.kind == "avwap" and node.output == "vwap" else node.output
            return ast.Ref(node.kind, ref_label(node.label), output, pos=pos)
        case ast.News():
            kwargs = tuple(sorted((k, canonicalize(v)) for k, v in node.kwargs))
            return ast.News(node.name, tuple(canonicalize(a) for a in node.args), kwargs, pos=pos)
        case ast.Offset():
            return ast.Offset(canonicalize(node.expr), node.bars, pos=pos)
        case ast.Timeframe():
            return ast.Timeframe(node.timeframe, canonicalize(node.expr), pos=pos)
        case ast.Neg():
            return ast.Neg(canonicalize(node.expr), pos=pos)
        case ast.Not():
            return ast.Not(canonicalize(node.expr), pos=pos)
        case ast.BinOp():
            return ast.BinOp(node.op, canonicalize(node.left), canonicalize(node.right), pos=pos)
        case ast.Compare():
            return ast.Compare(node.op, canonicalize(node.left), canonicalize(node.right), pos=pos)
        case ast.Cross():
            return ast.Cross(node.op, canonicalize(node.left), canonicalize(node.right), pos=pos)
        case ast.And():
            return ast.And(_sorted(ast.And, node.operands), pos=pos)
        case ast.Or():
            return ast.Or(_sorted(ast.Or, node.operands), pos=pos)
    return node


def ref_label(label: str) -> str:
    """A drawing label as rules match it: trimmed, inner spaces collapsed, lowercase."""
    return " ".join(label.split()).lower()


def rule_hash(canonical_text: str) -> str:
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


__all__ = ["canonicalize", "ref_label", "rule_hash"]
