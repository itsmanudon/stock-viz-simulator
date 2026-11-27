"""India capital gains rules for listed equity, dated and cited (A7.12, M10.7).

The owner's 27 Nov 2026 instruction: build from the Finance Act text for FY
2026-27, cite each rate, mark every figure as an estimate; the whole module
goes to the pre-release legal review. Every number below carries its source.

Scope: listed equity shares (and equity-oriented fund units) sold on a
recognised Indian exchange with securities transaction tax (STT) paid, held by
a resident individual. Not covered: unlisted shares, debt, F&O, buybacks, NRI
withholding, the basic-exemption-limit shortfall and the rebate (the rebate is
not available on these gains).

**Source reading note (27 Nov 2026).** Every source here was read through
search engine extracts, not by opening the page: the Income Tax Department's
section pages refuse automated reads (HTTP 403), and the news and law-firm
pages were cross-checked only through those extracts. Where nothing was read
the source says so. The legal review must confirm every rate and section
number against the enacted Income-tax Act, 2025 and the Finance Act, 2026.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    read_on: str = "2026-11-27"
    note: str = ""


@dataclass(frozen=True)
class FyRules:
    fy: str
    start: date
    end: date
    act: str
    stcg_section: str
    ltcg_section: str
    stcg_rate: Decimal
    ltcg_rate: Decimal
    ltcg_exemption: Decimal
    cess_rate: Decimal
    surcharge_cap: Decimal
    long_term_after_months: int
    sources: tuple[Source, ...]


ITD_196 = Source(
    "Income-tax Act, 2025, section 196: Tax on short-term capital gains in certain cases",
    "https://www.incometaxindia.gov.in/w/section-196-76",
    note="Page refuses automated reads; text from search extracts.",
)
ITD_198 = Source(
    "Income-tax Act, 2025, section 198: long-term capital gains exceeding Rs 1,25,000 at 12.5%",
    "https://www.incometaxindia.gov.in/w/section-198-76",
    note="Page refuses automated reads; text from search extracts.",
)
BUDGET_2026 = Source(
    "Budget 2026: LTCG tax rates unchanged for FY27 (Business Standard, 1 Feb 2026)",
    "https://www.business-standard.com/budget/news/budget-2026-ltcg-tax-rates-unchanged-for-fy27-fm-sitharaman-126020100424_1.html",
)
ANGEL_2026 = Source(
    "Union Budget 2026: LTCG tax unchanged at 12.5% (Angel One)",
    "https://www.angelone.in/news/taxation/union-budget-2026-ltcg-tax-unchanged-at-12-5-stt-on-commodity-futures-hiked",
)
KHAITAN_2025 = Source(
    "Khaitan & Co, Income-tax Bill 2025: capital gains (grandfathering at FMV on 31 Jan 2018 unchanged)",
    "https://khaitanco.com/sites/default/files/2025-03/CTC%20-%20Capital%20Gains%20&%20Corporate%20Re-organisation.pdf",
)
SEARCH_2024 = Source(
    "Rates of 20% (STCG) and 12.5% over Rs 1.25 lakh (LTCG) for transfers from 23 Jul 2024, "
    "carried unchanged into FY 2026-27",
    "https://www.angelone.in/news/taxation/union-budget-2026-ltcg-tax-unchanged-at-12-5-stt-on-commodity-futures-hiked",
    note="The Finance (No. 2) Act, 2024 itself was not read; to confirm in the legal review.",
)
FIFO_CIRCULAR = Source(
    "CBDT Circular No. 768 (24 Jun 1998): FIFO for shares held in demat form",
    "",
    note="Not read online for this build; named from the circular's number, to confirm.",
)

FY_RULES: dict[str, FyRules] = {
    "2025-26": FyRules(
        fy="2025-26",
        start=date(2025, 4, 1),
        end=date(2026, 3, 31),
        act="Income-tax Act, 1961 (as amended by the Finance (No. 2) Act, 2024)",
        stcg_section="111A",
        ltcg_section="112A",
        stcg_rate=Decimal("0.20"),
        ltcg_rate=Decimal("0.125"),
        ltcg_exemption=Decimal("125000"),
        cess_rate=Decimal("0.04"),
        surcharge_cap=Decimal("0.15"),
        long_term_after_months=12,
        sources=(SEARCH_2024, BUDGET_2026, KHAITAN_2025, FIFO_CIRCULAR),
    ),
    "2026-27": FyRules(
        fy="2026-27",
        start=date(2026, 4, 1),
        end=date(2027, 3, 31),
        act="Income-tax Act, 2025 (in force from 1 Apr 2026), read with the Finance Act, 2026",
        stcg_section="196",
        ltcg_section="198",
        stcg_rate=Decimal("0.20"),
        ltcg_rate=Decimal("0.125"),
        ltcg_exemption=Decimal("125000"),
        cess_rate=Decimal("0.04"),
        surcharge_cap=Decimal("0.15"),
        long_term_after_months=12,
        sources=(ITD_196, ITD_198, BUDGET_2026, ANGEL_2026, KHAITAN_2025, FIFO_CIRCULAR),
    ),
}

GRANDFATHER_CUTOFF = date(2018, 2, 1)
GRANDFATHER_FMV_DATE = date(2018, 1, 31)
LOSS_CARRY_YEARS = 8

ESTIMATE_NOTE = (
    "An estimate for information, not tax advice or a computation for filing. Rates are "
    "cited per rule and go to a legal review; your own figures depend on your full income, "
    "surcharge band, losses brought forward and transfer expenses."
)


def fy_of(day: date) -> str:
    """'2026-27' for any date from 1 Apr 2026 to 31 Mar 2027."""
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def is_long_term(bought: date, sold: date, months: int = 12) -> bool:
    """Held for more than ``months`` months (a sale on the anniversary is still short)."""
    year = bought.year + (bought.month - 1 + months) // 12
    month = (bought.month - 1 + months) % 12 + 1
    try:
        anniversary = bought.replace(year=year, month=month)
    except ValueError:  # 29-31 of a short month: the month's last day
        from calendar import monthrange

        anniversary = date(year, month, monthrange(year, month)[1])
    return sold > anniversary
