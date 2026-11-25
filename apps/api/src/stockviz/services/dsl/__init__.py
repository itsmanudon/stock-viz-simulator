"""The Rule DSL (A2.1): one rule language behind screens, alerts and setups.

``compile_rule(text)`` parses, type-checks and canonicalizes (``RuleError``
with line and column on failure); ``vector`` and ``point`` evaluate it on a
:class:`SymbolData`; ``evaluate_at`` judges one bar with its reasons.
See ``apps/api/CLAUDE.md`` ("Rule DSL (A2.1)") and ``docs/rule-dsl.md``.
"""

from stockviz.services.dsl.data import Needs, SymbolData, load_symbol
from stockviz.services.dsl.evaluate import (
    CompiledRule,
    ExplainRow,
    Outcome,
    compile_rule,
    evaluate_at,
    point,
    vector,
)
from stockviz.services.dsl.parser import RuleError, parse

__all__ = [
    "CompiledRule",
    "ExplainRow",
    "Needs",
    "Outcome",
    "RuleError",
    "SymbolData",
    "compile_rule",
    "evaluate_at",
    "load_symbol",
    "parse",
    "point",
    "vector",
]
