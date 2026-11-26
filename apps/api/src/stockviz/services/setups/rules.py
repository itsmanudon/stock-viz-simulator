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
            ("drawings", needs.drawings),
            ("daily_bars", needs.daily),
        )
        if used
    ]


def compile_number(text: str) -> CompiledRule:
    """A4.4: a numeric expression (a rotation's ranking). Raises
    :class:`RuleError` for a syntax or type error, or a condition."""
    rule = compile_rule(text, require_condition=False)
    if rule.type.value != "number":
        raise RuleError(
            "type",
            "a ranking must be a number (e.g. pct_change(close, 126)), not a condition",
            1,
            1,
            text=text,
        )
    return rule


def check_rule(text: str, expect: str = "condition", timeframe: str = "daily") -> RuleCheckOut:
    """A6.4: ``timeframe`` checks the rule for intraday bars (``daily.``,
    the per-binding refusals, warm-up in that timeframe's bars)."""
    try:
        if expect == "number":
            if timeframe != "daily":
                raise RuleError("type", "a ranking is judged on daily bars", 1, 1, text=text)
            rule = compile_number(text)
        else:
            rule = compile_rule(text, timeframe=timeframe)
    except RuleError as exc:
        return RuleCheckOut(valid=False, error=error_out(exc), timeframe=timeframe)
    return RuleCheckOut(
        valid=True,
        canonical=rule.canonical_text,
        hash=rule.hash,
        type=str(rule.type),
        warmup_bars=rule.lookback,
        warmup_whole_history=rule.lookback is None,
        uses=uses(rule),
        user_scoped=rule.user_scoped,
        timeframe=timeframe,
    )


def compile_or_422(text: str, timeframe: str = "daily") -> CompiledRule:
    try:
        return compile_rule(text, timeframe=timeframe)
    except RuleError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error_out(exc).model_dump()
        ) from exc


__all__ = ["check_rule", "compile_number", "compile_or_422", "error_out", "uses"]
