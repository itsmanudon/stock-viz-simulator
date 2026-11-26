"""Rule DSL syntax tree (A2.1): frozen dataclasses, compared by value.

Every node carries ``pos`` (line, column, both from 1) for error messages.
``pos`` takes no part in equality or hashing, so a rule parsed from
differently spaced text gives an equal tree, and ``parse(print(tree)) ==
tree`` holds.

The parser builds the tree as written (keyword arguments as keywords,
defaults left out). :func:`stockviz.services.dsl.canonical.canonicalize`
rewrites it into the one canonical tree that is printed and hashed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

Pos = tuple[int, int]


@dataclass(frozen=True)
class Node:
    pos: Pos | None = field(default=None, compare=False, hash=False, repr=False, kw_only=True)

    def children(self) -> tuple[Node, ...]:
        return ()


@dataclass(frozen=True)
class Num(Node):
    value: float


@dataclass(frozen=True)
class Str(Node):
    """A string literal. The grammar allows one only as a keyword value."""

    value: str


@dataclass(frozen=True)
class Name(Node):
    """A bar series: ``open high low close volume delivery_pct deliverable_qty``."""

    name: str


@dataclass(frozen=True)
class Call(Node):
    """``name(args, key=value)``, optionally ``.output`` for a multi-output indicator."""

    name: str
    args: tuple[Node, ...] = ()
    kwargs: tuple[tuple[str, Node], ...] = ()
    output: str | None = None

    def children(self) -> tuple[Node, ...]:
        return (*self.args, *(v for _k, v in self.kwargs))


@dataclass(frozen=True)
class News(Node):
    """``news.count(n, sentiment="...", event_type="...")``."""

    name: str
    args: tuple[Node, ...] = ()
    kwargs: tuple[tuple[str, Node], ...] = ()

    def children(self) -> tuple[Node, ...]:
        return (*self.args, *(v for _k, v in self.kwargs))


@dataclass(frozen=True)
class Fundamental(Node):
    """``fundamental.<metric>``: a point-in-time value as known on each bar."""

    metric: str


@dataclass(frozen=True)
class Ref(Node):
    """A3.3: a reference to one of the rule owner's chart drawings.

    ``drawing("label").price`` (``.top`` / ``.bottom`` for a rectangle) or
    ``avwap("label")`` (``.upper1 .lower1 .upper2 .lower2`` for its bands).
    User-scoped: it resolves only with the owner's drawings loaded."""

    kind: str  # "drawing" | "avwap"
    label: str
    output: str | None = None


@dataclass(frozen=True)
class Offset(Node):
    """``expr[n]``: the value ``n`` bars ago at the expression's own timeframe."""

    expr: Node
    bars: int

    def children(self) -> tuple[Node, ...]:
        return (self.expr,)


@dataclass(frozen=True)
class Timeframe(Node):
    """``weekly.expr`` / ``monthly.expr``: evaluated on resampled bars, then
    aligned to each daily bar as the last closed period at or before it.
    A6.4: ``daily.expr`` on an intraday timeframe, aligned to the session
    before each bar's."""

    timeframe: str  # "daily" | "weekly" | "monthly"
    expr: Node

    def children(self) -> tuple[Node, ...]:
        return (self.expr,)


@dataclass(frozen=True)
class Neg(Node):
    expr: Node

    def children(self) -> tuple[Node, ...]:
        return (self.expr,)


@dataclass(frozen=True)
class BinOp(Node):
    op: str  # + - * /
    left: Node
    right: Node

    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass(frozen=True)
class Compare(Node):
    op: str  # < <= > >= = !=
    left: Node
    right: Node

    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass(frozen=True)
class Cross(Node):
    op: str  # crosses_above | crosses_below
    left: Node
    right: Node

    def children(self) -> tuple[Node, ...]:
        return (self.left, self.right)


@dataclass(frozen=True)
class Not(Node):
    expr: Node

    def children(self) -> tuple[Node, ...]:
        return (self.expr,)


@dataclass(frozen=True)
class And(Node):
    operands: tuple[Node, ...]

    def children(self) -> tuple[Node, ...]:
        return self.operands


@dataclass(frozen=True)
class Or(Node):
    operands: tuple[Node, ...]

    def children(self) -> tuple[Node, ...]:
        return self.operands


def walk(node: Node) -> Iterator[Node]:
    """Every node, parents before children, in written order."""
    yield node
    for child in node.children():
        yield from walk(child)


__all__ = [
    "And",
    "BinOp",
    "Call",
    "Compare",
    "Cross",
    "Fundamental",
    "Name",
    "Neg",
    "News",
    "Node",
    "Not",
    "Num",
    "Offset",
    "Or",
    "Pos",
    "Ref",
    "Str",
    "Timeframe",
    "walk",
]
