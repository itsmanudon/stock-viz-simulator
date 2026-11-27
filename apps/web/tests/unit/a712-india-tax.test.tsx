// A7.12: the India tax view states the estimate first, cites rules and lists lots.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IndiaTaxView } from "@/components/india-tax-view";
import { type IndiaTax, inr, parseTaxParams } from "@/lib/india-tax";

const data: IndiaTax = {
  book_id: 3,
  fy: "2026-27",
  as_of: "2026-11-27",
  surcharge_rate: "0",
  rules: {
    fy: "2026-27",
    start: "2026-04-01",
    end: "2027-03-31",
    act: "Income-tax Act, 2025",
    stcg_section: "196",
    ltcg_section: "198",
    stcg_rate: "0.20",
    ltcg_rate: "0.125",
    ltcg_exemption: "125000",
    cess_rate: "0.04",
    surcharge_cap: "0.15",
    long_term_after_months: 12,
    sources: [
      { title: "Section 198", url: "https://example.test/198", read_on: "2026-11-27", note: "" },
    ],
  },
  computation: {
    stcg: "0",
    stcl: "0",
    ltcg: "60000",
    ltcl: "0",
    net_short: "0",
    net_long_before_exemption: "60000",
    exemption_used: "60000",
    exemption_left: "65000",
    taxable_short: "0",
    taxable_long: "0",
    tax_short: "0",
    tax_long: "0",
    surcharge: "0",
    cess: "0",
    total_tax: "0",
    loss_carried_short: "0",
    loss_carried_long: "0",
    intraday_pnl: "0",
  },
  realised: [
    {
      ticker: "TCS.NS",
      bought: "2025-01-06",
      sold: "2026-05-04",
      quantity: "60",
      cost: "180000",
      proceeds: "240000",
      gain: "60000",
      term: "long",
      grandfathered: false,
    },
  ],
  intraday: [],
  open_lots: [
    {
      ticker: "TCS.NS",
      bought: "2026-06-01",
      quantity: "20",
      cost: "70000",
      close: "3400",
      close_date: "2026-11-20",
      unrealised: "-2000",
      term: "short",
      long_term_on: "2027-06-02",
    },
  ],
  unmatched: [],
  skipped_tickers: [],
  method: ["Delivery by FIFO."],
  estimate_note: "An estimate for information, not tax advice.",
};

describe("India tax", () => {
  it("parses URL state and formats rupees with Indian grouping", () => {
    expect(parseTaxParams({ fy: "2019-20", surcharge: "0.37", book: "x" })).toEqual({
      fy: "2026-27",
      surcharge: 0,
      book: null,
    });
    expect(parseTaxParams({ fy: "2025-26", surcharge: "0.15", book: "4" }).book).toBe(4);
    expect(inr("125000")).toBe("₹1,25,000.00");
    expect(inr(null)).toBe("—");
  });

  it("puts the estimate note first and shows lots and sources", () => {
    render(<IndiaTaxView data={data} />);
    expect(screen.getByTestId("tax-estimate-note").textContent).toContain("not tax advice");
    expect(screen.getByText("Long Term")).toBeTruthy();
    expect(screen.getByTestId("tax-open-lot").dataset.term).toBe("short");
    expect(screen.getByText(/Short Term until 2027-06-02/)).toBeTruthy();
    expect(screen.getByTestId("tax-harvest-summary").textContent).toContain("not a recommendation");
    expect(screen.getByRole("link", { name: "Section 198" })).toBeTruthy();
  });
});
