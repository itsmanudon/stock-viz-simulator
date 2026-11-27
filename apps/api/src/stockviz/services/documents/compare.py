"""Compare a document with an earlier one: what changed, and how it is worded
(A9.10, M11.3). Deterministic: no model, nothing stored.

- **Section.** For 10-K/20-F style filings the risk factors are compared: the
  text from an "Item 1A. Risk Factors" heading to the next "Item 1B"/"Item 2"
  heading (the last such heading, so a table of contents is skipped). When
  either document has no such section, the whole texts are compared and the
  result says so.
- **Paragraph diff.** Paragraphs (blank-line separated, at least
  ``MIN_PARAGRAPH`` characters, whitespace collapsed) are matched with
  ``difflib.SequenceMatcher`` over their normalised text: ``added``,
  ``removed`` and ``changed`` (a replaced paragraph whose best partner is at
  least ``CHANGED_RATIO`` similar; below that it is a removal plus an
  addition). ``unchanged`` is counted, not listed.
- **Hedging.** Hedging and uncertainty phrases (``HEDGES``, a short fixed
  list in the spirit of the Loughran-McDonald uncertainty words, not that
  list itself) per 1,000 words, in each document, and the change. A rough
  signal of wording, not of evasiveness or intent; the method says so.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

MIN_PARAGRAPH = 40
CHANGED_RATIO = 0.6
MAX_LISTED = 60
SECTION_START = re.compile(r"(?im)^\s*item\s*1a\.?\s*[-:\u2013\u2014]?\s*risk\s+factors\b")
SECTION_END = re.compile(r"(?im)^\s*item\s*(1b|1c|2)\.?\s")
HEDGES = (
    "may", "might", "could", "possibly", "possible", "perhaps", "uncertain", "uncertainty",
    "uncertainties", "approximately", "roughly", "depend", "depends", "depending",
    "believe", "believes", "expect", "expects", "anticipate", "anticipates", "likely",
    "unlikely", "potential", "potentially", "assume", "assumes", "estimate", "estimates",
    "subject to", "we think", "sort of", "kind of", "to some extent", "at this point",
    "too early", "difficult to say", "hard to say", "going forward",
)  # fmt: skip
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@dataclass(frozen=True)
class Change:
    kind: str  # added | removed | changed
    before: str | None
    after: str | None
    similarity: float | None


@dataclass
class Hedging:
    words: int
    hedges: int
    per_thousand: float | None
    top: list[tuple[str, int]]


@dataclass
class Comparison:
    scope: str  # risk_factors | whole_text
    scope_note: str | None
    paragraphs_before: int
    paragraphs_after: int
    unchanged: int
    added: int
    removed: int
    changed: int
    changes: list[Change] = field(default_factory=list)
    truncated: bool = False
    hedging_before: Hedging | None = None
    hedging_after: Hedging | None = None


def risk_factors(text: str) -> str | None:
    """The risk factors section, or None when there is no such heading."""
    starts = list(SECTION_START.finditer(text))
    if not starts:
        return None
    start = starts[-1].start()
    end = SECTION_END.search(text, starts[-1].end())
    body = text[start : end.start() if end else len(text)].strip()
    return body if len(body) >= MIN_PARAGRAPH else None


def paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", text):
        p = " ".join(block.split())
        if len(p) >= MIN_PARAGRAPH:
            out.append(p)
    return out


def _norm(p: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", p.lower())


def hedging(text: str) -> Hedging:
    low = " ".join(text.lower().split())
    words = len(WORD.findall(low))
    counts: dict[str, int] = {}
    for h in HEDGES:
        n = len(re.findall(rf"\b{re.escape(h)}\b", low))
        if n:
            counts[h] = n
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return Hedging(words, total, round(1000 * total / words, 2) if words else None, top)


def compare(before: str, after: str) -> Comparison:
    rb, ra = risk_factors(before), risk_factors(after)
    if rb is not None and ra is not None:
        scope, note, b_text, a_text = "risk_factors", None, rb, ra
    else:
        missing = (
            "neither"
            if rb is None and ra is None
            else ("the earlier" if rb is None else "the later")
        )
        scope, b_text, a_text = "whole_text", before, after
        note = f"No risk factors section found in {missing} document; whole texts compared."
    pb, pa = paragraphs(b_text), paragraphs(a_text)
    nb, na = [_norm(p) for p in pb], [_norm(p) for p in pa]
    out = Comparison(scope, note, len(pb), len(pa), 0, 0, 0, 0)
    sm = difflib.SequenceMatcher(a=nb, b=na, autojunk=False)
    changes: list[Change] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.unchanged += i2 - i1
            continue
        old, new = list(range(i1, i2)), list(range(j1, j2))
        used: set[int] = set()
        for i in old:
            best, best_r = None, 0.0
            for j in new:
                if j in used:
                    continue
                r = difflib.SequenceMatcher(a=nb[i], b=na[j], autojunk=False).ratio()
                if r > best_r:
                    best, best_r = j, r
            if best is not None and best_r >= CHANGED_RATIO:
                used.add(best)
                out.changed += 1
                changes.append(Change("changed", pb[i], pa[best], round(best_r, 3)))
            else:
                out.removed += 1
                changes.append(Change("removed", pb[i], None, None))
        for j in new:
            if j not in used:
                out.added += 1
                changes.append(Change("added", None, pa[j], None))
    out.truncated = len(changes) > MAX_LISTED
    out.changes = changes[:MAX_LISTED]
    out.hedging_before, out.hedging_after = hedging(b_text), hedging(a_text)
    return out
