"""A7.10 (M5.5, M1.9 India): the documents module.

Files are written by each test; EDGAR answers are hand-written in the
documented shape. No test reaches the SEC.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from stockviz import cli
from stockviz.models import Document, DocumentText
from stockviz.services.documents import edgar, load
from stockviz.services.documents.extract import (
    MAX_PDF_PAGES,
    PDF_SCANNED_REASON,
    ExtractError,
    extract,
    html_text,
)
from stockviz.services.documents.store import NewDocument, add_document, search, snippets
from stockviz.services.instruments import instrument_ids
from tests.symbols import seed_symbols

HTML = b"""<html><head><title>x</title><style>.a{}</style></head><body>
<div style="display:none"><ix:header>hidden xbrl</ix:header></div>
<script>var tracking = 1;</script>
<h1>Quarterly Results</h1><p>Revenue grew   12%&nbsp;year on year.</p>
<table><tr><td>Margin</td><td>21%</td></tr></table></body></html>"""


# --- extraction -----------------------------------------------------------


def test_html_text_drops_scripts_styles_and_hidden_xbrl() -> None:
    text = html_text(HTML)
    assert "tracking" not in text and "hidden xbrl" not in text and ".a{}" not in text
    assert "Quarterly Results" in text
    assert "Revenue grew 12% year on year." in text
    assert "Margin" in text and "21%" in text


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF, one Helvetica text line per page (no text when blank)."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, line in enumerate(pages):
        body = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode() if line else b""
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
            f"<< /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % k + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def test_pdf_text_is_read_page_by_page() -> None:
    got = extract(make_pdf(["Order book grew 18 percent", "Margin guidance 21 percent"]), "pdf")
    assert got.content_type == "pdf"
    assert "Order book grew 18 percent" in got.text and "Margin guidance 21 percent" in got.text
    assert got.text.index("Order book") < got.text.index("Margin")


def test_bad_scanned_and_empty_files_are_refused_with_the_reason() -> None:
    with pytest.raises(ExtractError, match="not a readable PDF"):
        extract(b"%PDF-1.7 truncated", "pdf")
    with pytest.raises(ExtractError, match="OCR"):
        extract(make_pdf(["", ""]), "pdf")
    assert "scanned" in PDF_SCANNED_REASON
    with pytest.raises(ExtractError, match=f"more than {MAX_PDF_PAGES} pages"):
        extract(make_pdf(["x"] * (MAX_PDF_PAGES + 1)), "pdf")
    with pytest.raises(ExtractError, match="no text"):
        extract(b"   \n  ", "text")


def test_snippets_mark_cut_text() -> None:
    text = "a" * 200 + " order book grew " + "b" * 200
    (one,) = snippets(text, "ORDER BOOK")
    assert one.startswith("…") and one.endswith("…") and "order book grew" in one


# --- file loader ----------------------------------------------------------


def _files(tmp_path: Path) -> list[Path]:
    a = tmp_path / "TCS_Q2_concall.html"
    a.write_bytes(HTML)
    b = tmp_path / "notes.md"
    b.write_text("Management guided to double-digit growth in FY27.\n", encoding="utf-8")
    c = tmp_path / "deck.pdf"
    c.write_bytes(make_pdf(["Q2 deck: revenue up 9 percent"]))
    d = tmp_path / "sheet.xlsx"
    d.write_bytes(b"PK")
    return [a, b, c, d]


def test_dry_run_writes_nothing_then_apply_stores_and_reruns_dedupe(
    session: Session, tmp_path: Path
) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    paths = _files(tmp_path)
    dry = load.load_files(
        session, paths, ticker="tcs.ns", kind="concall_transcript", on=date(2026, 10, 9)
    )
    assert [f.status for f in dry.files] == ["new", "new", "new", "refused"]
    assert session.exec(select(Document)).all() == []
    # 9 Oct 23:59 IST is 18:29 UTC; marked assumed.
    assert dry.available_at == datetime(2026, 10, 9, 18, 29) and dry.available_assumed

    done = load.load_files(
        session, paths, ticker="TCS.NS", kind="concall_transcript", on=date(2026, 10, 9), apply=True
    )
    assert [f.status for f in done.files][:3] == ["stored", "stored", "stored"]
    docs = session.exec(select(Document)).all()
    assert len(docs) == 3 and all(d.source == "file" and d.available_assumed for d in docs)
    assert {d.title for d in docs} == {"TCS Q2 concall", "notes", "deck"}
    pdf = next(d for d in docs if d.title == "deck")
    pdf_text = session.get(DocumentText, pdf.id)
    assert pdf.content_type == "pdf" and pdf_text is not None and "revenue up 9" in pdf_text.text
    text = session.get(DocumentText, docs[0].id)
    assert text is not None and text.text

    again = load.load_files(
        session, paths, ticker="TCS.NS", kind="concall_transcript", on=date(2026, 10, 9), apply=True
    )
    assert [f.status for f in again.files][:3] == ["duplicate"] * 3
    assert len(session.exec(select(Document)).all()) == 3


def test_an_explicit_release_time_is_not_assumed(session: Session, tmp_path: Path) -> None:
    seed_symbols(session, "AAPL")
    out = load.load_files(
        session,
        _files(tmp_path)[1:2],
        ticker="AAPL",
        kind="announcement",
        available_at=datetime.fromisoformat("2026-10-30T16:30:00-04:00"),
    )
    assert out.available_at == datetime(2026, 10, 30, 20, 30) and not out.available_assumed


def test_loader_refusals(session: Session, tmp_path: Path, monkeypatch) -> None:
    seed_symbols(session, "AAPL")
    with pytest.raises(load.LoadRefused, match="no instrument"):
        load.load_files(session, [], ticker="NOPE", kind="filing", on=date(2026, 1, 1))
    with pytest.raises(load.LoadRefused, match="available-at"):
        load.load_files(session, [], ticker="AAPL", kind="filing")
    with pytest.raises(load.LoadRefused, match="kind must be"):
        load.load_files(session, [], ticker="AAPL", kind="memo", on=date(2026, 1, 1))
    monkeypatch.setattr(load, "local_database_problem", lambda url: "the host is remote")
    with pytest.raises(load.LoadRefused, match="local database only"):
        load.load_files(session, [], ticker="AAPL", kind="filing", on=date(2026, 1, 1))


# --- EDGAR ----------------------------------------------------------------

SUBMISSIONS: dict[str, Any] = {
    "cik": "320193",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-26-000105",
                "0000320193-26-000090",
                "0000320193-25-000010",
            ],
            "filingDate": ["2026-10-31", "2026-08-01", "2025-02-01"],
            "reportDate": ["2026-09-27", "2026-06-28", "2024-12-28"],
            "acceptanceDateTime": [
                "2026-10-31T06:01:36.000Z",
                "2026-08-01T16:30:00.000Z",
                "2025-02-01T06:00:00.000Z",
            ],
            "form": ["10-K", "4", "10-Q"],
            "primaryDocument": ["aapl-20260927.htm", "form4.xml", "aapl-20241228.htm"],
            "primaryDocDescription": ["10-K", "FORM 4", "10-Q"],
        }
    },
}


def test_parse_submissions_keeps_wanted_forms_and_reads_acceptance_as_new_york() -> None:
    filings = edgar.parse_submissions(SUBMISSIONS, 320193)
    assert [f.form for f in filings] == ["10-K", "10-Q"]
    k = filings[0]
    assert k.url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000105/aapl-20260927.htm"
    )
    # 06:01:36 New York (EDT) is 10:01:36 UTC: never earlier than the Z reading.
    assert k.available_at == datetime(2026, 10, 31, 10, 1, 36)
    assert k.report_date == date(2026, 9, 27)


def test_sync_edgar_stores_new_filings_once(session: Session) -> None:
    seed_symbols(session, "AAPL")
    fetched: list[str] = []

    def get_json(url: str) -> dict[str, Any]:
        assert url.endswith("CIK0000320193.json")
        return SUBMISSIONS

    def get_bytes(url: str) -> bytes:
        fetched.append(url)
        return HTML.replace(b"Quarterly", url.rsplit("/", 1)[-1].encode())

    first = edgar.sync_edgar(
        session,
        ["AAPL"],
        since=date(2025, 1, 1),
        get_json=get_json,
        get_bytes=get_bytes,
        ciks={"AAPL": 320193},
    )
    assert first[0].stored == 2 and first[0].error is None
    docs = session.exec(select(Document).order_by(col(Document.available_at))).all()
    assert [d.kind for d in docs] == ["filing", "annual_report"]
    assert docs[1].title.startswith("10-K for 2026-09-27") and docs[1].source == "edgar"
    again = edgar.sync_edgar(
        session,
        ["AAPL"],
        since=date(2025, 1, 1),
        get_json=get_json,
        get_bytes=get_bytes,
        ciks={"AAPL": 320193},
    )
    assert again[0].stored == 0 and again[0].skipped == 2 and len(fetched) == 2
    late = edgar.sync_edgar(
        session,
        ["MSFT"],
        since=date(2025, 1, 1),
        get_json=get_json,
        get_bytes=get_bytes,
        ciks={"AAPL": 320193},
    )
    assert late[0].error == "no CIK"


def test_docs_edgar_is_off_without_a_user_agent(monkeypatch, capsys) -> None:
    from stockviz.settings import get_settings

    monkeypatch.setenv("SEC_USER_AGENT", "")
    get_settings.cache_clear()
    try:
        assert cli.main(["docs-edgar", "AAPL", "--since", "2026-01-01"]) == 2
    finally:
        get_settings.cache_clear()
    assert "SEC_USER_AGENT" in capsys.readouterr().err


# --- reads and routes -----------------------------------------------------


def _store(session: Session, ticker: str, title: str, text: str, at: datetime) -> int:
    iid = instrument_ids(session, [ticker])[ticker]
    from stockviz.services.documents.extract import Extracted

    doc, _ = add_document(
        session,
        NewDocument(
            instrument_id=iid,
            kind="concall_transcript",
            source="file",
            title=title,
            available_at=at,
        ),
        text.encode(),
        Extracted("text", text),
    )
    session.commit()
    assert doc.id is not None
    return doc.id


def test_routes_list_search_and_read_point_in_time(client: TestClient, session: Session) -> None:
    seed_symbols(session, "TCS.NS", currency="INR")
    old = _store(
        session, "TCS.NS", "Q1", "Order book was strong. Order book grew.", datetime(2026, 7, 10)
    )
    future = _store(session, "TCS.NS", "Q9", "Order book from the future.", datetime(2099, 1, 1))

    listed = client.get("/v1/symbols/tcs.ns/documents").json()
    assert [d["id"] for d in listed["documents"]] == [old]
    early = client.get("/v1/symbols/TCS.NS/documents?as_of=2026-07-01T00:00:00").json()
    assert early["documents"] == []

    found = client.get("/v1/documents/search?q=order%20book&ticker=TCS.NS").json()
    assert [h["document"]["id"] for h in found["hits"]] == [old]
    assert found["hits"][0]["matches"] == 2 and found["hits"][0]["document"]["ticker"] == "TCS.NS"
    assert "Order book" in found["hits"][0]["snippets"][0]
    # The LIKE pattern is escaped: a percent sign matches only itself.
    assert client.get("/v1/documents/search?q=%25%25").json()["hits"] == []

    detail = client.get(f"/v1/documents/{old}?q=grew").json()
    assert detail["text"].startswith("Order book") and detail["matches"] == 1
    assert client.get(f"/v1/documents/{future}").status_code == 404
    assert client.get("/v1/symbols/TCS.NS/documents?kind=memo").status_code == 400
    assert client.get("/v1/symbols/NOPE/documents").status_code == 404


def test_search_without_a_ticker_covers_every_symbol(session: Session) -> None:
    seed_symbols(session, "AAPL", "MSFT")
    _store(session, "AAPL", "a", "Services revenue rose.", datetime(2026, 1, 5))
    _store(session, "MSFT", "m", "Azure revenue rose.", datetime(2026, 1, 6))
    hits = search(session, "revenue rose", as_of=datetime(2026, 2, 1))
    assert [h.document.title for h in hits] == ["m", "a"]
