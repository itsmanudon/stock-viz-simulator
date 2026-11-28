"""The filings copilot: answers from stored passages, with citations (A8.5, M11.2).

One question in, one answer out; nothing is stored. The pipeline:

1. ``retrieve`` the best passages (A8.4's hybrid search, point-in-time on
   ``as_of``). None found: no model call, a fixed "not in the documents".
2. The model gets numbered sources and the question, with rules: answer only
   from the sources, put ``[n]`` after every claim, say when the sources do not
   cover it, never recommend buying or selling.
3. ``check_citations`` keeps what the model wrote but marks it: citation
   numbers that name no source are listed and removed from ``cited``; an answer
   citing no valid source is ``grounded = False``; each sentence without a
   citation is counted. Nothing the model says is trusted beyond the text shown.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session

from stockviz.services.ai.embed import Embedder
from stockviz.services.ai.provider import LLMProvider, Message
from stockviz.services.documents import retrieve

MAX_SOURCES = 10  # 6 until 28 Nov 2026; see CLAUDE.md "Copilot eval"
MAX_SOURCE_CHARS = 1_400
NOT_FOUND = "The stored documents do not cover this."
SYSTEM = f"""You answer questions about companies using ONLY the numbered sources given.
Rules:
- Every sentence that states a fact ends with the number of its source in square brackets, e.g. [2]. Use only numbers of the sources given.
- If the sources do not answer the question, reply exactly: {NOT_FOUND}
- Do not use outside knowledge. Do not guess figures. Quote figures as the source states them.
- Never recommend buying, selling or holding anything, and give no price targets.
- Be brief: at most six sentences."""

CITATION = re.compile(r"\[(\d{1,2})(?:\s*,\s*(\d{1,2}))*\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
LEADING_CITES = re.compile(r"^((?:\[\d{1,2}(?:\s*,\s*\d{1,2})*\]\s*)+)")


def sentences(text: str) -> list[str]:
    """Sentences split at . ! ? followed by space (so "24.6" stays whole); a
    citation written after the full stop ("... quarter. [1]") joins its sentence."""
    out: list[str] = []
    for piece in SENTENCE_END.split(text.strip()):
        piece = piece.strip()
        if not piece:
            continue
        lead = LEADING_CITES.match(piece)
        if lead and out:
            out[-1] = f"{out[-1]} {lead.group(1).strip()}"
            piece = piece[lead.end() :].strip()
            if not piece:
                continue
        out.append(piece)
    return out


@dataclass
class CitationCheck:
    cited: list[int]
    invalid: list[int]
    uncited_sentences: int
    grounded: bool


@dataclass
class CopilotAnswer:
    question: str
    retrieval: retrieve.Retrieval
    sources: list[retrieve.Passage]
    answer: str | None
    check: CitationCheck | None
    provider: str | None = None
    model: str | None = None
    warnings: list[str] = field(default_factory=list)


def _numbers(text: str) -> list[int]:
    out: list[int] = []
    for m in CITATION.finditer(text):
        for n in re.findall(r"\d{1,2}", m.group(0)):
            out.append(int(n))
    return out


def check_citations(answer: str, n_sources: int) -> CitationCheck:
    nums = _numbers(answer)
    valid = sorted({n for n in nums if 1 <= n <= n_sources})
    invalid = sorted({n for n in nums if not 1 <= n <= n_sources})
    uncited = 0
    if answer.strip() != NOT_FOUND:
        for sentence in sentences(answer):
            if len(sentence.split()) >= 4 and not CITATION.search(sentence):
                uncited += 1
    return CitationCheck(valid, invalid, uncited, grounded=bool(valid))


def build_messages(
    question: str,
    sources: list[retrieve.Passage],
    tickers: dict[int, str],
    system: str = SYSTEM,
) -> list[Message]:
    lines = []
    for i, p in enumerate(sources, start=1):
        doc = p.document
        when = doc.available_at.strftime("%Y-%m-%d")
        head = f"[{i}] {tickers.get(doc.instrument_id, '?')} · {doc.title} · public {when}"
        about = f"\n(About this passage: {p.context})" if p.context else ""
        lines.append(f"{head}{about}\n{p.text[:MAX_SOURCE_CHARS]}")
    user = "Sources:\n\n" + "\n\n".join(lines) + f"\n\nQuestion: {question}"
    return [Message("system", system), Message("user", user)]


# Words that are company-name first words but also ordinary words: never used alone.
_COMMON_FIRST = frozenset(
    [
        "american",
        "bank",
        "first",
        "general",
        "home",
        "international",
        "national",
        "new",
        "united",
        "the",
        "global",
        "world",
        "capital",
        "energy",
        "health",
        "digital",
    ]
)
_NAME_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|group|"
    r"holdings|platforms|n\.?v|s\.?a)\.?$",
    re.I,
)


def name_aliases(ticker: str, name: str | None) -> set[str]:
    """How a question might name a company: its ticker, its name, its name's first word."""
    out = {ticker.split(".")[0].upper()}
    core = (name or "").strip()
    core = re.sub(r"^the\s+", "", core, flags=re.I)
    for _ in range(3):
        core = _NAME_SUFFIX.sub("", core).strip()
    if core and core.upper() != ticker.upper():
        out.add(core.lower())
        first = re.split(r"[\s&]", core)[0].lower()
        if len(first) >= 4 and first not in _COMMON_FIRST:
            out.add(first)
    return out


def named_instrument(question: str, companies: Mapping[int, tuple[str, str | None]]) -> int | None:
    """The one company (by instrument id) a question names, else None.

    ``companies`` maps instrument id to (ticker, name) for companies with stored
    documents. Tickers match as upper-case words of at least two letters
    ("AAPL", not "v"); names match case-insensitively as whole words.
    Two companies named, or none, gives None: the search stays over all.
    """
    hits: set[int] = set()
    for iid, (ticker, name) in companies.items():
        for alias in name_aliases(ticker, name):
            if alias.isupper():
                if len(alias) >= 2 and re.search(
                    rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])", question
                ):
                    hits.add(iid)
            elif re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", question.lower()):
                hits.add(iid)
    return hits.pop() if len(hits) == 1 else None


def ask(
    session: Session,
    provider: LLMProvider,
    question: str,
    *,
    as_of: datetime,
    ticker_names: Callable[[set[int]], dict[int, str]],
    instrument_id: int | None = None,
    kind: str | None = None,
    embedder: Embedder | None = None,
    companies: Mapping[int, tuple[str, str | None]] | None = None,
) -> CopilotAnswer:
    """``companies`` (id -> ticker, name): with no ``instrument_id``, a question
    naming exactly one of them searches that company's documents only."""
    q = " ".join(question.split())
    scoped = None
    if instrument_id is None and companies:
        instrument_id = scoped = named_instrument(q, companies)
    found = retrieve.retrieve(
        session, q, as_of=as_of, instrument_id=instrument_id, kind=kind,
        limit=MAX_SOURCES, embedder=embedder,
    )  # fmt: skip
    if scoped is not None and companies is not None:
        found.notes.append(
            f"The question names {companies[scoped][0]}: searched its documents only."
        )
    out = CopilotAnswer(
        question=q, retrieval=found, sources=found.passages, answer=None, check=None
    )
    if not found.passages:
        out.answer = NOT_FOUND
        out.warnings.append("No stored passage matched, so no model was asked.")
        return out
    tickers = ticker_names({p.document.instrument_id for p in found.passages})
    return answer_from(provider, out, tickers)


def answer_from(
    provider: LLMProvider,
    out: CopilotAnswer,
    tickers: dict[int, str],
    *,
    system: str = SYSTEM,
    not_found: str = NOT_FOUND,
) -> CopilotAnswer:
    """Ask ``provider`` about ``out.sources`` and check the citations into ``out``."""
    text = provider.complete(build_messages(out.question, out.sources, tickers, system)).strip()
    out.provider, out.model = provider.name, provider.model
    out.answer = text
    out.check = check_citations(text, len(out.sources))
    if out.check.invalid:
        out.warnings.append(
            "The model cited sources that do not exist: "
            + ", ".join(f"[{n}]" for n in out.check.invalid)
            + "."
        )
    if text != not_found and not out.check.grounded:
        out.warnings.append("The answer cites no source: treat it as unsupported.")
    elif out.check.uncited_sentences:
        out.warnings.append(
            f"{out.check.uncited_sentences} sentence(s) carry no citation: check them against "
            "the sources."
        )
    return out
