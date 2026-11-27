"""Figures out of a document, each checked against the text (A9.10, M11.3).

The model reads up to ``MAX_PASSAGES`` passages that contain a digit and
returns a JSON list of ``{metric, value, unit, period, quote}``. Nothing it
says is kept unless it checks out:

- ``quote`` must appear in the passages word for word (whitespace and case
  aside), and
- every digit run of ``value`` must appear in that quote ("64,259" must be in
  "Revenue was 64,259 crore").

Dropped items are counted by reason, never shown as figures. Nothing is
stored; a figure's passage is returned so it can be read in place.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from stockviz.models import DocumentChunk
from stockviz.services.ai.provider import LLMProvider, Message

MAX_PASSAGES = 8
MAX_ITEMS = 30
SYSTEM = """You extract reported figures from company documents.
Return ONLY a JSON array, no prose. Each item:
{"metric": "short name", "value": "the figure exactly as written", "unit": "currency, %, crore, shares... or empty", "period": "quarter, year or date it refers to, or empty", "quote": "the sentence containing it, copied exactly"}
Rules: only figures stated in the passages; copy "value" and "quote" character for character; no calculations, no estimates, no figures from memory. At most 30 items. If there are none, return []."""


@dataclass(frozen=True)
class Figure:
    metric: str
    value: str
    unit: str
    period: str
    quote: str
    chunk_id: int


@dataclass
class Extraction:
    figures: list[Figure]
    passages: list[DocumentChunk]
    dropped: dict[str, int] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def passages_with_numbers(session: Session, document_id: int) -> list[DocumentChunk]:
    rows = session.exec(
        select(DocumentChunk)
        .where(col(DocumentChunk.document_id) == document_id)
        .order_by(col(DocumentChunk.position))
    ).all()
    return [c for c in rows if re.search(r"\d", c.text)][:MAX_PASSAGES]


def parse_items(raw: str) -> list[dict] | None:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        items = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else None


def verify(items: list[dict], passages: list[DocumentChunk]) -> tuple[list[Figure], dict[str, int]]:
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    norm_passages = [(c, _norm(c.text)) for c in passages]
    out: list[Figure] = []
    seen: set[tuple[str, str]] = set()
    for item in items[:MAX_ITEMS]:
        quote = str(item.get("quote") or "").strip()
        value = str(item.get("value") or "").strip()
        metric = str(item.get("metric") or "").strip()[:80]
        if not quote or not value or not metric:
            drop("incomplete")
            continue
        nq = _norm(quote)
        home = next((c for c, t in norm_passages if nq in t), None)
        if home is None:
            drop("quote not in the text")
            continue
        digits = re.findall(r"\d+", value)
        if not digits or not all(d in quote for d in digits):
            drop("value not in its quote")
            continue
        key = (metric.lower(), value)
        if key in seen:
            drop("duplicate")
            continue
        seen.add(key)
        assert home.id is not None
        out.append(
            Figure(
                metric=metric,
                value=value[:60],
                unit=str(item.get("unit") or "").strip()[:40],
                period=str(item.get("period") or "").strip()[:60],
                quote=quote[:500],
                chunk_id=home.id,
            )
        )
    return out, dropped


def extract(session: Session, provider: LLMProvider, document_id: int) -> Extraction:
    passages = passages_with_numbers(session, document_id)
    result = Extraction(figures=[], passages=passages)
    if not passages:
        return result
    body = "\n\n".join(f"Passage {i}:\n{c.text}" for i, c in enumerate(passages, start=1))
    raw = provider.complete([Message("system", SYSTEM), Message("user", body)])
    result.provider, result.model = provider.name, provider.model
    items = parse_items(raw)
    if items is None:
        result.dropped = {"answer was not a JSON list": 1}
        return result
    result.figures, result.dropped = verify(items, passages)
    return result
