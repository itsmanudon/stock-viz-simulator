"""Copilot eval (A8, 27 Nov 2026): retrieval and answers on real filings, scored without a judge.

The questions (``copilot_eval_questions.json``) were written by Claude Opus 5.5
from passages of EDGAR 10-K/10-Q filings of 25 US tickers; each ``answer`` is
copied from its passage (checked when the set was made). Ten negatives: five
ask for advice, five ask what the filings cannot answer.

Rebuild the corpus on a LOCAL database, then run:

    uv run python -m stockviz.cli docs-edgar AAPL ADBE AMZN BAC CRM CSCO DIS GOOGL HD INTC \\
        JNJ JPM KO MA META MSFT NFLX NVDA PFE PG TSLA UNH V WMT XOM \\
        --since 2025-01-01 --forms 10-K 10-Q --limit 5
    uv run python -m stockviz.cli docs-index --embed
    uv run python scripts/copilot_eval.py --models ollama,claude-haiku-5-5

Scores per model, all on the same retrieved passages:
- ``correct``: every digit run of the answer is in the reply ("$94,930" -> 94930);
- ``cited right``: a cited source contains the answer;
- ``negatives``: the exact not-found reply for questions the filings cannot
  answer, and for advice questions no buy/sell/hold or target unless the
  reply declines to give one;
- retrieval: how often the answer is in the six passages at all.

Claude models need ``ANTHROPIC_API_KEY`` (environment or ``apps/api/.env``)
and are billed; Ollama is local. Questions are re-run against whatever
filings the database holds, so a newer filing set can change the numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, col, select

from stockviz.db import engine
from stockviz.models import Document, DocumentChunk
from stockviz.routers.ai import _companies_with_documents
from stockviz.routers.documents import _tickers
from stockviz.services.ai import copilot
from stockviz.services.ai.embed import embedder_from_settings
from stockviz.services.ai.provider import LLMProvider, OllamaProvider
from stockviz.services.documents import retrieve
from stockviz.settings import get_settings

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "copilot_eval_questions.json"
DECLINED = re.compile(r"\b(can(no|')t|won't|will not|do not|don't|unable to|not able to)\b", re.I)
ADVICE = re.compile(
    r"\b(you should|i recommend|i would (buy|sell|hold)|good investment|price target (is|of))",
    re.I,
)


def digit_runs(value: str) -> list[str]:
    return [d.replace(",", "") for d in re.findall(r"\d[\d,.]*\d|\d", value)]


def contains(text: str, answer: str) -> bool:
    flat = text.replace(",", "")
    return all(d in flat for d in digit_runs(answer))


def _anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    env = HERE.parent / ".env"
    if not key and env.exists():
        vals = [
            line.split("=", 1)[1].strip().strip("\"'")
            for line in env.read_text().splitlines()
            if line.startswith("ANTHROPIC_API_KEY=")
        ]
        key = next((v for v in reversed(vals) if v), "")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    return key


def provider(name: str) -> LLMProvider:
    if name == "ollama":
        return OllamaProvider(model=get_settings().ollama_model or "gemma4:e4b")
    from stockviz.services.ai.claude import ClaudeProvider

    return ClaudeProvider(model=name, api_key=_anthropic_key())


def score(item: dict, out: copilot.CopilotAnswer, gold_chunk: int | None) -> dict:
    reply = (out.answer or "").strip()
    row = {"question": item["question"], "kind": item["kind"], "reply": reply}
    if item["kind"] == "figure":
        row["retrieved"] = any(contains(p.text, item["answer"]) for p in out.sources)
        row["gold_passage"] = any(p.chunk_id == gold_chunk for p in out.sources)
        row["correct"] = reply != copilot.NOT_FOUND and contains(reply, item["answer"])
        cited = out.check.cited if out.check else []
        row["cited_right"] = any(
            contains(out.sources[n - 1].text, item["answer"])
            for n in cited
            if n <= len(out.sources)
        )
    elif item["kind"] == "absent":
        row["passed"] = reply == copilot.NOT_FOUND
    else:
        # Advice given, unless the reply declines it ("I can't say whether X is a good investment").
        row["passed"] = not ADVICE.search(reply) or bool(DECLINED.search(reply))
    row["invalid_citations"] = out.check.invalid if out.check else []
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", default="ollama", help="Comma-separated: ollama, claude-*")
    ap.add_argument("--all-companies", action="store_true", help="Do not scope by company named")
    ap.add_argument("--out", help="Write every reply and score to this JSON file")
    args = ap.parse_args()
    items = json.loads(QUESTIONS.read_text())
    embedder = embedder_from_settings(get_settings())
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        companies = {} if args.all_companies else _companies_with_documents(session)
        found, gold = [], []
        for item in items:
            q = " ".join(item["question"].split())
            iid = copilot.named_instrument(q, companies) if companies else None
            found.append(
                retrieve.retrieve(
                    session,
                    q,
                    as_of=now,
                    limit=copilot.MAX_SOURCES,
                    embedder=embedder,
                    instrument_id=iid,
                )
            )
            chunk = None
            if item["kind"] == "figure":
                chunk = session.exec(
                    select(col(DocumentChunk.id))
                    .join(Document, col(Document.id) == col(DocumentChunk.document_id))
                    .where(col(Document.accession) == item["accession"])
                    .where(col(DocumentChunk.position) == item["position"])
                ).first()
            gold.append(chunk)
        names = _tickers(session, {p.document.instrument_id for r in found for p in r.passages})
    if not any(r.passages for r in found):
        print("no passages: load the corpus first (see the docstring)", file=sys.stderr)
        return 2
    report = {}
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        llm = provider(name)

        def one(i: int, llm: LLMProvider = llm) -> dict:
            r = found[i]
            out = copilot.CopilotAnswer(
                question=r.query, retrieval=r, sources=r.passages, answer=None, check=None
            )
            if r.passages:
                copilot.answer_from(llm, out, names)
            else:
                out.answer = copilot.NOT_FOUND
            return score(items[i], out, gold[i])

        with ThreadPoolExecutor(1 if name == "ollama" else 6) as pool:
            rows = list(pool.map(one, range(len(items))))
        report[name] = rows
        fig = [r for r in rows if r["kind"] == "figure"]
        neg = [r for r in rows if r["kind"] != "figure"]
        print(
            f"{name:22} correct {sum(r['correct'] for r in fig)}/{len(fig)}"
            f" (when retrieved {sum(r['correct'] for r in fig if r['retrieved'])}"
            f"/{sum(r['retrieved'] for r in fig)})"
            f" | cited right {sum(r['cited_right'] for r in fig)}"
            f" | invalid citations {sum(bool(r['invalid_citations']) for r in rows)}"
            f" | negatives {sum(r['passed'] for r in neg)}/{len(neg)}"
        )
    first = next(iter(report.values()))
    fig = [r for r in first if r["kind"] == "figure"]
    print(
        f"retrieval: answer in the top {copilot.MAX_SOURCES} for {sum(r['retrieved'] for r in fig)}"
        f"/{len(fig)}; the question's own passage for {sum(r['gold_passage'] for r in fig)}/{len(fig)}"
    )
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
