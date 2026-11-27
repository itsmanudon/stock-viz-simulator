"""Research grid and case for / case against, from stored passages (A9.11,
M11.4, M11.5). Built on A8.5's copilot: same retrieval, same citation check,
nothing stored.

- **Grid** (M11.4): up to ``MAX_TICKERS`` companies by ``MAX_QUESTIONS``
  questions; each cell is one copilot answer limited to that company's
  documents, so a cell can only cite its own company. A cell with no passage
  makes no model call.
- **Case for / case against** (M11.5): one company and a topic; the same
  passages go to the model twice, once to argue the case for and once the
  case against, each only from the sources and with ``[n]`` citations, each
  ending with what would weaken it. Both sides are shown together and
  neither is a recommendation; the prompts forbid buy/sell/hold and targets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from stockviz.services.ai import copilot
from stockviz.services.ai.embed import Embedder
from stockviz.services.ai.provider import LLMProvider
from stockviz.services.documents import retrieve

MAX_TICKERS = 5
MAX_QUESTIONS = 3
DEBATE_SOURCES = 8
NO_CASE = "The stored documents give no basis for this side."

_SIDE = """You argue ONE side of an investment debate about a company, using ONLY the numbered sources given.
Side: {side}.
Rules:
- Make at most four points, each one or two sentences, as a plain numbered list (no headings, no bold).
- Every sentence that states a fact ends with the number of its source in square brackets, e.g. [2].
- Use only facts in the sources; no outside knowledge, no invented figures.
- End with one sentence starting "Would weaken this side:" naming what in the sources, or what new fact, would weaken it, cited if it comes from a source.
- If the sources give no basis for this side, reply exactly: {none}
- Never recommend buying, selling or holding, and give no price targets."""
CASE_FOR = _SIDE.format(side="the case FOR the business (strengths, tailwinds)", none=NO_CASE)
CASE_AGAINST = _SIDE.format(side="the case AGAINST the business (weaknesses, risks)", none=NO_CASE)


@dataclass
class GridCell:
    ticker: str
    question: str
    answer: copilot.CopilotAnswer


@dataclass
class Debate:
    ticker: str
    topic: str
    retrieval: retrieve.Retrieval
    case_for: copilot.CopilotAnswer
    case_against: copilot.CopilotAnswer


def grid(
    session: Session,
    provider: LLMProvider,
    companies: list[tuple[str, int]],
    questions: list[str],
    *,
    as_of: datetime,
    ticker_names: Callable[[set[int]], dict[int, str]],
    embedder: Embedder | None = None,
) -> list[GridCell]:
    cells: list[GridCell] = []
    for ticker, iid in companies[:MAX_TICKERS]:
        for q in questions[:MAX_QUESTIONS]:
            ans = copilot.ask(
                session, provider, q, as_of=as_of, ticker_names=ticker_names,
                instrument_id=iid, embedder=embedder,
            )  # fmt: skip
            cells.append(GridCell(ticker, ans.question, ans))
    return cells


def debate(
    session: Session,
    provider: LLMProvider,
    ticker: str,
    instrument_id: int,
    topic: str,
    *,
    as_of: datetime,
    ticker_names: Callable[[set[int]], dict[int, str]],
    embedder: Embedder | None = None,
) -> Debate:
    t = " ".join(topic.split())
    found = retrieve.retrieve(
        session, t, as_of=as_of, instrument_id=instrument_id, limit=DEBATE_SOURCES,
        embedder=embedder,
    )  # fmt: skip

    def side(system: str) -> copilot.CopilotAnswer:
        out = copilot.CopilotAnswer(
            question=t, retrieval=found, sources=found.passages, answer=None, check=None
        )
        if not found.passages:
            out.answer = NO_CASE
            out.warnings.append("No stored passage matched, so no model was asked.")
            return out
        names = ticker_names({p.document.instrument_id for p in found.passages})
        return copilot.answer_from(provider, out, names, system=system, not_found=NO_CASE)

    return Debate(ticker, t, found, side(CASE_FOR), side(CASE_AGAINST))
