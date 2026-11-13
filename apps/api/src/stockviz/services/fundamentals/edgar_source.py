"""Fundamentals from SEC EDGAR company facts (Phase 6.3; off until configured).

Free, no key, but the SEC asks automated clients to send a User-Agent with a
contact (``SEC_USER_AGENT``). The owner sets it before release, with the other
legal items; until then this source is off and the command exits 2.

- ``company_tickers.json`` maps a ticker to its CIK.
- ``/api/xbrl/companyfacts/CIK##########.json`` holds every XBRL fact, each
  with its period, value, form and **filing date**: ``available_at`` is the
  filing date, so these rows are point-in-time.
- Durations of about three months are quarters, about a year are annual;
  year-to-date durations are skipped. Facts without a start are instants.
- Only 10-K, 10-Q and their amendments count.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from stockviz.services.fundamentals.concepts import CONCEPTS, EDGAR, unit_for
from stockviz.services.fundamentals.store import FactRecord

SOURCE = "edgar"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
REQUEST_GAP_SECONDS = 0.15  # well under the SEC's 10 requests a second

GetJson = Callable[[str], dict[str, Any]]


class EdgarNotConfigured(RuntimeError):
    pass


def http_getter(user_agent: str) -> GetJson:
    if not user_agent.strip():
        raise EdgarNotConfigured("SEC_USER_AGENT is not set")

    def get(url: str) -> dict[str, Any]:
        time.sleep(REQUEST_GAP_SECONDS)
        response = httpx.get(url, headers={"User-Agent": user_agent}, timeout=30.0)
        response.raise_for_status()
        return response.json()

    return get


def cik_map(get: GetJson) -> dict[str, int]:
    return {row["ticker"].upper(): int(row["cik_str"]) for row in get(TICKERS_URL).values()}


def _period(start: str | None, end: str) -> str | None:
    if start is None:
        return "instant"
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    if 80 <= days <= 100:
        return "quarter"
    if 350 <= days <= 380:
        return "annual"
    return None  # year-to-date or odd lengths


def parse_facts(payload: dict[str, Any]) -> list[FactRecord]:
    facts = payload.get("facts", {})
    chosen: dict[tuple, FactRecord] = {}
    for concept_key, tags in EDGAR.items():
        concept = CONCEPTS[concept_key]
        for tag in tags:
            namespace, name = tag.split(":")
            units = facts.get(namespace, {}).get(name, {}).get("units", {})
            for unit_name, entries in units.items():
                currency = unit_name.split("/")[0] if unit_name != "shares" else None
                for e in entries:
                    if e.get("form") not in FORMS or "filed" not in e or "end" not in e:
                        continue
                    period_type = _period(e.get("start"), e["end"])
                    if period_type is None:
                        continue
                    if concept.kind == "stock" and period_type != "instant":
                        continue
                    if concept.kind == "flow" and period_type == "instant":
                        continue
                    value = Decimal(str(e["val"]))
                    if concept.outflow:
                        value = abs(value)
                    rec = FactRecord(
                        concept=concept_key,
                        period_type=period_type,
                        period_start=date.fromisoformat(e["start"]) if e.get("start") else None,
                        period_end=date.fromisoformat(e["end"]),
                        value=value,
                        unit=unit_for(concept, currency),
                        currency=currency,
                        available_at=date.fromisoformat(e["filed"]),
                        point_in_time=True,
                        source=SOURCE,
                        source_concept=tag,
                        fiscal_year=e.get("fy"),
                        fiscal_period=e.get("fp"),
                        form=e.get("form"),
                        accession=e.get("accn"),
                    )
                    key = (concept_key, period_type, rec.period_end, rec.available_at)
                    # The first (preferred) tag with a value for a period wins.
                    chosen.setdefault(key, rec)
    return list(chosen.values())


def fetch_facts(symbol: str, *, get: GetJson, ciks: dict[str, int]) -> list[FactRecord]:
    cik = ciks.get(symbol.upper())
    if cik is None:
        raise LookupError(f"{symbol} has no CIK in company_tickers.json")
    return parse_facts(get(FACTS_URL.format(cik=cik)))
