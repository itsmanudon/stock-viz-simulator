"""Plain English to Rule DSL (A8.2, M4.2 translator half).

The model drafts DSL text only. ``setups.rules.check_rule`` judges it, exactly
as the screener's editor does; the user then decides whether to use it.
Nothing runs on a draft. When the check fails the model gets one more try
with the error; a draft that still fails comes back with its error, never
silently changed.

The prompt is built from the live function registry (names and parameter
defaults), so a new study is described without editing this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from stockviz.schemas import RuleCheckOut
from stockviz.services.ai.provider import LLMProvider, Message
from stockviz.services.dsl.bindings import FUNDAMENTAL_METRICS
from stockviz.services.dsl.functions import FUNCTIONS
from stockviz.services.setups.rules import check_rule

MAX_ATTEMPTS = 2
MAX_INPUT_CHARS = 500

GRAMMAR = """\
Write one Rule DSL condition and nothing else: no prose, no code fences.
Grammar:
- Series: open high low close volume delivery_pct index_close.
- Numbers, + - * /, comparisons < <= > >= = != (never chained), and/or/not, parentheses.
- crosses_above / crosses_below between two series, e.g. sma(close, 20) crosses_above sma(close, 50).
- [n] looks n bars back: close[1] is the previous close.
- weekly. or monthly. before a series or call reads the last closed week or month.
- fundamental.<metric> (metrics listed below) is a point-in-time value: compare it,
  never offset or cross it.
- news.count(days, sentiment="positive"|"negative"|"neutral") counts linked news.
- Function names are lowercase; arguments by position; omitted ones take the defaults below.
- Percentages are in percent, never fractions: pct_change(close) > 5 is "up more than 5%";
  fundamental.roe > 18 is "ROE above 18%". Every fundamental needs the fundamental. prefix.
Examples:
- "price above its 200-day average and RSI under 30" -> close > sma(close, 200) and rsi(14) < 30
- "volume more than twice its 20-day average" -> volume > 2 * sma(volume, 20)
- "MACD crosses its signal line" -> macd() crosses_above macd().signal
- "within 5% of the 52-week high" -> close >= 0.95 * highest(high, 252)
- "up more than 4% on the day" -> pct_change(close) > 4
- "P/E below 20 and ROE above 15%" -> fundamental.pe < 20 and fundamental.roe > 15
"""


def function_catalogue() -> str:
    lines = []
    for name in sorted(FUNCTIONS):
        spec = FUNCTIONS[name]
        params = ", ".join(
            p.name if p.default is None else f"{p.name}={p.default:g}" for p in spec.params
        )
        outputs = f" outputs: {', '.join(spec.outputs)}" if len(spec.outputs) > 1 else ""
        doc = f" - {spec.doc}" if spec.doc else ""
        lines.append(f"{name}({params}){outputs}{doc}")
    return "\n".join(lines)


def system_prompt() -> str:
    metrics = ", ".join(FUNDAMENTAL_METRICS)
    return f"{GRAMMAR}\nFundamental metrics: {metrics}\nFunctions:\n{function_catalogue()}"


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def extract_rule(answer: str) -> str:
    """The rule out of a model answer: fences and a leading label removed, first line."""
    text = _FENCE.sub("", answer.strip()).strip()
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        if not line or line.startswith("#"):
            continue
        return re.sub(r"^(rule|dsl|answer)\s*:\s*", "", line, flags=re.IGNORECASE)
    return ""


@dataclass
class Attempt:
    rule: str
    check: RuleCheckOut


@dataclass
class Translation:
    request: str
    provider: str
    model: str
    rule: str
    check: RuleCheckOut
    attempts: list[Attempt] = field(default_factory=list)


def translate(provider: LLMProvider, request: str, *, timeframe: str = "daily") -> Translation:
    text = request.strip()[:MAX_INPUT_CHARS]
    messages = [Message("system", system_prompt()), Message("user", text)]
    attempts: list[Attempt] = []
    for _ in range(MAX_ATTEMPTS):
        rule = extract_rule(provider.complete(messages))
        check = check_rule(rule or " ", timeframe=timeframe)
        attempts.append(Attempt(rule, check))
        if check.valid:
            break
        error = check.error.message if check.error else "not a valid rule"
        messages += [
            Message("assistant", rule),
            Message(
                "user", f"That rule fails the check: {error}. Reply with a corrected rule only."
            ),
        ]
    last = attempts[-1]
    return Translation(text, provider.name, provider.model, last.rule, last.check, attempts)
