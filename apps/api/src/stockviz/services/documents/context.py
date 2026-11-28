"""Contextual passages (A8.8, M11.1): a model writes one line per passage.

A passage cut from a long filing often names neither the company nor the
period ("Net sales increased 8%..."). ``generate`` asks a model for a short
line that situates it (company, filing, period, section, what it covers);
retrieval searches and embeds that line together with the text
(``retrieve.SEARCH_TEXT_SQL``, ``index.embed_input``) and the copilot shows it
to the answering model as "About this passage". It is never quoted as the
filing's words: citations are still checked against the passage text.

Measured on 27-28 Nov 2026 (120 EDGAR filings, 35,336 passages, Claude Haiku
5.5 writing the lines): with Haiku answering, the copilot went from 148 to
179 of 199 figure questions, and from 176 to 231 of 320 harder ones
(paraphrased, company described not named, exact period).

Setting a context clears the passage's vector, so ``docs-index --embed``
re-embeds it. Lines are kept with the model that wrote them and can be moved
between databases by filing accession and passage position (``export`` /
``import_rows``), so a paid run is never repeated.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlmodel import Session, col, func, select

from stockviz.models import Document, DocumentChunk, DocumentText
from stockviz.services.ai.provider import AiProviderError, LLMProvider, Message

MAX_CONTEXT_CHARS = 600
BEFORE_CHARS = 6_000
AFTER_CHARS = 1_500
COVER_CHARS = 1_500
_HEADING = re.compile(r"(?im)^\s*(item\s+\d+[a-z]?\.?[^\n]{0,80}|part\s+i{1,3}v?\b[^\n]{0,60})$")

PROMPT = """<document_info>
Company: {company}. Filing: {form} for the period ending {period}.
Section (nearest heading before the passage): {section}
</document_info>
<cover_page>
{cover}
</cover_page>
<surrounding_text>
{window}
</surrounding_text>
<passage>
{passage}
</passage>
Write one short context (at most 50 words) that situates the passage within this filing, to improve search retrieval of the passage. Name the company, the filing and period, the section, and what the passage's figures or statements are about (for example "net sales by product category for the three and nine months ended June 27, 2026"). Answer with the context only."""


@dataclass
class ContextReport:
    written: int = 0
    failed: int = 0
    waiting: int = 0
    notes: list[str] = field(default_factory=list)


def section_of(text: str, start: int) -> str:
    """The nearest "Item N" / "Part N" heading at or before ``start``; "unknown" if none."""
    found = "unknown"
    for m in _HEADING.finditer(text, 0, start):
        found = " ".join(m.group(1).split())
    return found


def build_prompt(company: str, doc: Document, full_text: str, chunk: DocumentChunk) -> str:
    start, end = chunk.start_char, chunk.end_char
    return PROMPT.format(
        company=company,
        form=doc.form_type or doc.kind,
        period=doc.event_date or "unknown",
        section=section_of(full_text, start),
        cover=full_text[:COVER_CHARS],
        window=full_text[max(0, start - BEFORE_CHARS) : start]
        + "[PASSAGE]"
        + full_text[end : end + AFTER_CHARS],
        passage=chunk.text,
    )


def clean(reply: str) -> str | None:
    line = " ".join(reply.split()).strip().strip('"')
    return line[:MAX_CONTEXT_CHARS] if len(line) >= 20 else None


def set_context(chunk: DocumentChunk, context: str, model: str) -> None:
    """Store a context; the vector is cleared so ``docs-index --embed`` redoes it."""
    chunk.context = context
    chunk.context_model = model
    chunk.embedding = None
    chunk.embed_model = None


def _pending(limit: int | None):
    stmt = (
        select(DocumentChunk)
        .where(col(DocumentChunk.context).is_(None))
        .order_by(col(DocumentChunk.document_id), col(DocumentChunk.position))
    )
    return stmt.limit(limit) if limit else stmt


def waiting(session: Session) -> int:
    return session.exec(
        select(func.count()).select_from(DocumentChunk).where(col(DocumentChunk.context).is_(None))
    ).one()


def generate(
    session: Session,
    provider: LLMProvider,
    companies: dict[int, str],
    *,
    limit: int | None = None,
) -> ContextReport:
    """One model call per passage without a context; a failed or empty reply is skipped."""
    report = ContextReport()
    texts: dict[int, tuple[Document, str]] = {}
    for chunk in session.exec(_pending(limit)).all():
        if chunk.document_id not in texts:
            doc = session.get(Document, chunk.document_id)
            body = session.get(DocumentText, chunk.document_id)
            if doc is None or body is None:
                report.failed += 1
                continue
            texts[chunk.document_id] = (doc, body.text)
        doc, full = texts[chunk.document_id]
        prompt = build_prompt(companies.get(doc.instrument_id, "?"), doc, full, chunk)
        try:
            line = clean(provider.complete([Message("user", prompt)]))
        except AiProviderError as exc:
            report.failed += 1
            if not report.notes:
                report.notes.append(str(exc))
            continue
        if line is None:
            report.failed += 1
            continue
        set_context(chunk, line, provider.model)
        session.add(chunk)
        session.commit()
        report.written += 1
    report.waiting = waiting(session)
    return report


def export(session: Session) -> Iterator[dict[str, object]]:
    """Every stored context keyed by filing accession and passage position."""
    rows = session.exec(
        select(Document.accession, DocumentChunk.position, DocumentChunk.context,
               DocumentChunk.context_model)
        .join(Document, col(Document.id) == col(DocumentChunk.document_id))
        .where(col(DocumentChunk.context).is_not(None), col(Document.accession).is_not(None))
        .order_by(col(Document.accession), col(DocumentChunk.position))
    ).all()  # fmt: skip
    for accession, position, context, model in rows:
        yield {"accession": accession, "position": position, "context": context, "model": model}


def import_rows(session: Session, rows: Iterable[dict[str, object]]) -> tuple[int, int]:
    """(applied, unmatched): rows whose accession and position name a stored passage."""
    where = {
        f"{accession}#{position}": chunk_id
        for accession, position, chunk_id in session.exec(
            select(Document.accession, DocumentChunk.position, DocumentChunk.id)
            .join(Document, col(Document.id) == col(DocumentChunk.document_id))
            .where(col(Document.accession).is_not(None))
        ).all()
    }
    applied = unmatched = 0
    for row in rows:
        chunk_id = where.get(f"{row.get('accession')}#{row.get('position')}")
        line = clean(str(row.get("context") or ""))
        if chunk_id is None or line is None:
            unmatched += 1
            continue
        session.exec(  # type: ignore[call-overload]
            update(DocumentChunk)
            .where(col(DocumentChunk.id) == chunk_id)
            .values(context=line, context_model=str(row.get("model") or "imported")[:64],
                    embedding=None, embed_model=None)
        )  # fmt: skip
        applied += 1
    session.commit()
    return applied, unmatched
