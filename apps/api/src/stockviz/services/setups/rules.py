"""Checking a rule for the API (A2.2): ``POST /v1/rules/check`` and every
endpoint that stores one (setups, theses, screens).

``check_rule`` never raises: it returns the canonical form or the error with
its line and column. ``compile_or_422`` is for writers: a rule that does not
compile is a 422 whose ``detail`` is the same error object.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from stockviz.schemas import RuleCheckOut, RuleErrorOut
from stockviz.services.dsl import CompiledRule, RuleError, compile_rule


def error_out(exc: RuleError) -> RuleErrorOut:
    kind = exc.kind if exc.kind in ("syntax", "type") else "syntax"
    return RuleErrorOut(kind=kind, message=exc.message, line=exc.line, column=exc.column)  # type: ignore[arg-type]


def uses(rule: CompiledRule) -> list[str]:
    needs = rule.needs
    return [
        name
        for name, used in (
            ("benchmark", needs.benchmark),
            ("fundamentals", needs.fundamentals),
            ("news", needs.news),
            ("delivery", needs.delivery),
        )
        if used
    ]


def check_rule(text: str) -> RuleCheckOut:
    try:
        rule = compile_rule(text)
    except RuleError as exc:
        return RuleCheckOut(valid=False, error=error_out(exc))
    return RuleCheckOut(
        valid=True,
        canonical=rule.canonical_text,
        hash=rule.hash,
        type=str(rule.type),
        warmup_bars=rule.lookback,
        warmup_whole_history=rule.lookback is None,
        uses=uses(rule),
    )


def compile_or_422(text: str) -> CompiledRule:
    try:
        return compile_rule(text)
    except RuleError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error_out(exc).model_dump()
        ) from exc


__all__ = ["check_rule", "compile_or_422", "error_out", "uses"]
