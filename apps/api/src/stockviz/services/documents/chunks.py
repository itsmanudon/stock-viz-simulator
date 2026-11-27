"""Split a document's text into overlapping passages (A8.4, M11.1).

Passages of about ``SIZE`` characters, cut at a paragraph break, else a line
break, else a sentence end, else a space, never mid-word unless a single word
is longer than ``SIZE``. Consecutive passages overlap by about ``OVERLAP`` so
a sentence across a cut is whole in one of them. Offsets index the stored text.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, col, select

from stockviz.models import DocumentChunk, DocumentText

SIZE = 1200
OVERLAP = 200
MIN_CUT = SIZE // 2
BREAKS = ("\n\n", "\n", ". ", " ")


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def spans(text: str, *, size: int = SIZE, overlap: int = OVERLAP) -> list[Span]:
    out: list[Span] = []
    n = len(text)
    start = 0
    while start < n:
        while start < n and text[start].isspace():
            start += 1
        if start >= n:
            break
        end = min(n, start + size)
        if end < n:
            window = text[start:end]
            for mark in BREAKS:
                cut = window.rfind(mark, size // 2)
                if cut > 0:
                    end = start + cut + len(mark)
                    break
        piece_end = end
        while piece_end > start and text[piece_end - 1].isspace():
            piece_end -= 1
        out.append(Span(start, piece_end))
        if end >= n:
            break
        nxt = max(start + 1, end - overlap)
        space = text.find(" ", nxt, end)
        start = space + 1 if space != -1 else nxt
    return out


def build_chunks(session: Session, document_id: int, text: str | None = None) -> int:
    """Replace the document's chunks from its text; returns how many."""
    if text is None:
        row = session.get(DocumentText, document_id)
        text = row.text if row else ""
    for old in session.exec(
        select(DocumentChunk).where(col(DocumentChunk.document_id) == document_id)
    ).all():
        session.delete(old)
    found = spans(text)
    for i, span in enumerate(found):
        session.add(
            DocumentChunk(
                document_id=document_id,
                position=i,
                start_char=span.start,
                end_char=span.end,
                text=text[span.start : span.end],
            )
        )
    return len(found)
