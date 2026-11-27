"""A8.1 (M4.2): every operand and comparator the visual builder writes compiles.

The web builder's catalogue (``apps/web/lib/rule-builder.ts``) is held equal to
``fixtures/rule_builder_operands.json`` by its Vitest test; this compiles each
entry against each comparator, as a condition and inside a two-group rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockviz.services.dsl import compile_rule
from stockviz.services.dsl.parser import RuleError

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "rule_builder_operands.json").read_text()
)


@pytest.mark.parametrize("operand", FIXTURE["operands"])
@pytest.mark.parametrize("comparator", FIXTURE["comparators"])
def test_each_operand_compiles_with_each_comparator(operand: str, comparator: str) -> None:
    if comparator.startswith("crosses") and operand.startswith("fundamental."):
        # Point-in-time values have no bar history: the builder offers no
        # crossing on them (``isPointInTime`` in rule-builder.ts), and the DSL refuses one.
        with pytest.raises(RuleError, match="point-in-time"):
            compile_rule(f"{operand} {comparator} 1")
        return
    compile_rule(f"{operand} {comparator} 1")
    compile_rule(f"close {comparator} {operand}" if comparator.startswith("crosses") else
                 f"{operand} {comparator} sma(close, 50)")  # fmt: skip


def test_groups_compile() -> None:
    rule = "(close > sma(close, 50) and rsi(14) >= 50) or fundamental.pe < 10"
    assert compile_rule(rule).type.value == "boolean"
