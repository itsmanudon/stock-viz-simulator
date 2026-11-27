"""US filings from SEC EDGAR (A7.10). Off until ``SEC_USER_AGENT`` is set.

The SEC asks automated clients for a User-Agent with a contact; the owner
sets it with the other pre-release legal items (as for the EDGAR
fundamentals), so until then the command exits 2. Tests answer from
hand-written fixtures; no test reaches the SEC.

- ``company_tickers.json`` maps a ticker to its CIK (shared with
  ``fundamentals/edgar_source.py``).
- ``https://data.sec.gov/submissions/CIK##########.json``: ``filings.recent``
  holds parallel arrays (``accessionNumber``, ``filingDate``, ``reportDate``,
  ``acceptanceDateTime``, ``form``, ``primaryDocument``,
  ``primaryDocDescription``).
- The primary document is at
  ``https://www.sec.gov/Archives/edgar/data/<cik>/<accession, no dashes>/<file>``.

``available_at``: the acceptance time's clock reading taken as New York time.
EDGAR writes a ``Z`` on it, but if that reading is really UTC this only makes a
filing count from a few hours later than it was public, never earlier.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
DEFAULT_FORMS = ("10-K", "10-Q", "8-K", "20-F", "6-K")
REQUEST_GAP_SECONDS = 0.15
NEW_YORK = ZoneInfo("America/New_York")

GetJson = Callable[[str], dict[str, Any]]
GetBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: date
    report_date: date | None
    available_at: datetime
    url: str
    description: str


def http_getters(user_agent: str) -> tuple[GetJson, GetBytes]:
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    def get_bytes(url: str) -> bytes:
        time.sleep(REQUEST_GAP_SECONDS)
        response = httpx.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.content

    def get_json(url: str) -> dict[str, Any]:
        time.sleep(REQUEST_GAP_SECONDS)
        response = httpx.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("EDGAR answered with something other than an object")
        return body

    return get_json, get_bytes


def _day(raw: object) -> date | None:
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def acceptance_instant(raw: object, filing_date: date) -> datetime:
    """Naive UTC; the clock reading read as New York time (see module docstring)."""
    if isinstance(raw, str) and len(raw) >= 19:
        try:
            local = datetime.fromisoformat(raw[:19]).replace(tzinfo=NEW_YORK)
            return local.astimezone(UTC).replace(tzinfo=None)
        except ValueError:
            pass
    # No time: the end of the filing date in New York.
    end = datetime.combine(filing_date, datetime.max.time(), tzinfo=NEW_YORK)
    return end.astimezone(UTC).replace(tzinfo=None, microsecond=0)


def parse_submissions(
    payload: dict[str, Any], cik: int, *, forms: tuple[str, ...] = DEFAULT_FORMS
) -> list[Filing]:
    recent = (payload.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    out: list[Filing] = []
    for i, accession in enumerate(accessions):

        def at(key: str, i: int = i) -> Any:
            values = recent.get(key) or []
            return values[i] if i < len(values) else None

        form = str(at("form") or "")
        if form not in forms:
            continue
        filed = _day(at("filingDate"))
        document = at("primaryDocument")
        if filed is None or not document or not isinstance(accession, str):
            continue
        out.append(
            Filing(
                accession=accession,
                form=form,
                filing_date=filed,
                report_date=_day(at("reportDate")),
                available_at=acceptance_instant(at("acceptanceDateTime"), filed),
                url=ARCHIVE_URL.format(
                    cik=cik, accession=accession.replace("-", ""), document=document
                ),
                description=str(at("primaryDocDescription") or form),
            )
        )
    return out


def list_filings(
    get_json: GetJson, cik: int, *, forms: tuple[str, ...] = DEFAULT_FORMS
) -> list[Filing]:
    return parse_submissions(get_json(SUBMISSIONS_URL.format(cik=cik)), cik, forms=forms)


@dataclass
class TickerSync:
    ticker: str
    stored: int = 0
    skipped: int = 0
    error: str | None = None


ANNUAL_FORMS = {"10-K", "20-F"}


def sync_edgar(
    session: Any,
    tickers: list[str],
    *,
    get_json: GetJson,
    get_bytes: GetBytes,
    ciks: dict[str, int],
    since: date,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    limit: int = 20,
) -> list[TickerSync]:
    """Store each ticker's newest filings (at most ``limit``) filed on or after ``since``."""
    from sqlmodel import select

    from stockviz.models import Document
    from stockviz.services.documents.extract import ExtractError, content_type_for, extract
    from stockviz.services.documents.store import NewDocument, add_document
    from stockviz.services.instruments import instrument_ids

    ids = instrument_ids(session, tickers)
    results: list[TickerSync] = []
    for ticker in tickers:
        result = TickerSync(ticker)
        results.append(result)
        cik = ciks.get(ticker.upper().replace("-", "."), ciks.get(ticker.upper()))
        if cik is None or ticker not in ids:
            result.error = "no CIK" if cik is None else "no instrument"
            continue
        try:
            filings = [
                f for f in list_filings(get_json, cik, forms=forms) if f.filing_date >= since
            ]
        except (httpx.HTTPError, ValueError) as exc:
            result.error = f"submissions failed ({exc.__class__.__name__})"
            continue
        filings.sort(key=lambda f: f.available_at, reverse=True)
        for filing in filings[:limit]:
            known = session.exec(
                select(Document.id).where(Document.accession == filing.accession)
            ).first()
            if known is not None:
                result.skipped += 1
                continue
            content_type = content_type_for(filing.url) or "html"
            try:
                data = get_bytes(filing.url)
                extracted = extract(data, content_type)
            except (httpx.HTTPError, ExtractError) as exc:
                result.skipped += 1
                result.error = f"{filing.accession}: {exc.__class__.__name__}"
                continue
            period = f" for {filing.report_date.isoformat()}" if filing.report_date else ""
            _, created = add_document(
                session,
                NewDocument(
                    instrument_id=ids[ticker],
                    kind="annual_report" if filing.form in ANNUAL_FORMS else "filing",
                    source="edgar",
                    title=f"{filing.form}{period}: {filing.description}",
                    available_at=filing.available_at,
                    event_date=filing.report_date or filing.filing_date,
                    form_type=filing.form,
                    url=filing.url,
                    accession=filing.accession,
                ),
                data,
                extracted,
            )
            session.commit()
            if created:
                result.stored += 1
            else:
                result.skipped += 1
    return results
