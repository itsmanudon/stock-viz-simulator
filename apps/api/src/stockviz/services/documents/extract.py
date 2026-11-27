"""Text out of a document's bytes (A7.10).

HTML (EDGAR primary documents, saved web pages) goes through BeautifulSoup's
built-in ``html.parser``: scripts, styles and hidden XBRL headers dropped, block
elements on their own lines, runs of spaces collapsed. Plain text and Markdown
are read as UTF-8 (Latin-1 as the fallback). PDFs (owner, 27 Nov 2026: ``pypdf``,
pure Python, no native code) are read page by page with layout-free extraction;
encrypted PDFs, PDFs over ``MAX_PDF_PAGES`` and scanned PDFs with no text layer
are refused with the reason (scans would need OCR, which is not added).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

CONTENT_TYPES = {".html": "html", ".htm": "html", ".txt": "text", ".md": "text", ".pdf": "pdf"}
MAX_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 600
PDF_SCANNED_REASON = "no text layer (a scanned PDF needs OCR, which is not added)"
BLOCKS = ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section")


class ExtractError(ValueError):
    """The bytes cannot become text; ``str()`` says why."""


@dataclass(frozen=True)
class Extracted:
    content_type: str
    text: str


def content_type_for(path: Path | str) -> str | None:
    return CONTENT_TYPES.get(Path(path).suffix.lower())


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def html_text(data: bytes) -> str:
    soup = BeautifulSoup(_decode(data), "html.parser")
    for tag in soup(["script", "style", "head", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        tag.decompose()
    for name in ("ix:header",):
        for tag in soup.find_all(name):
            tag.decompose()
    for tag in soup.find_all(BLOCKS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return _tidy(soup.get_text())


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractError("the PDF is encrypted")
        pages = reader.pages
        if len(pages) > MAX_PDF_PAGES:
            raise ExtractError(f"more than {MAX_PDF_PAGES} pages")
        parts = [page.extract_text() or "" for page in pages]
    except ExtractError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ExtractError(f"not a readable PDF ({type(exc).__name__})") from exc
    text = _tidy("\n\n".join(parts))
    if not text:
        raise ExtractError(PDF_SCANNED_REASON)
    return text


def extract(data: bytes, content_type: str) -> Extracted:
    if len(data) > MAX_BYTES:
        raise ExtractError(f"larger than {MAX_BYTES // (1024 * 1024)} MiB")
    if content_type == "pdf":
        text = pdf_text(data)
    elif content_type == "html":
        text = html_text(data)
    elif content_type == "text":
        text = _tidy(_decode(data))
    else:
        raise ExtractError("not a supported type (HTML, PDF, text or Markdown)")
    if not text:
        raise ExtractError("no text in the file")
    return Extracted(content_type, text)
