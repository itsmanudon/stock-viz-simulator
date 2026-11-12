import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FundamentalsPanel, ordinal } from "@/components/fundamentals-panel";
import type { Fundamentals, Valuation } from "@/lib/api/fundamentals";

const annual: Fundamentals = {
  ticker: "INFY.NS",
  period: "annual",
  as_of: "2026-11-12",
  currency: "USD",
  periods: ["2026-03-31", "2025-03-31"],
  rows: [
    { concept: "revenue", label: "Revenue", unit: "USD", values: ["20158000000", "19280000000"] },
    { concept: "eps_diluted", label: "EPS (diluted)", unit: "USD/share", values: ["0.78", null] },
  ],
  sources: ["yfinance"],
  point_in_time: false,
  latest_available_at: "2026-11-06",
};

const valuation: Valuation = {
  ticker: "INFY.NS",
  as_of: "2026-11-12",
  price: "1500",
  price_date: "2026-11-11",
  trading_currency: "INR",
  reporting_currency: "USD",
  fx_rate: "0.012",
  basis: "ttm",
  point_in_time: false,
  sources: ["yfinance"],
  metrics: [
    { key: "pe", label: "P/E", value: 18, unit: "x", reason: null },
    {
      key: "dividend_yield",
      label: "Dividend yield",
      value: null,
      unit: "%",
      reason: "no dividends reported",
    },
  ],
};

describe("FundamentalsPanel (Phase 6.4)", () => {
  it("labels period, currency, source and the currency conversion", () => {
    render(
      <FundamentalsPanel
        annual={annual}
        quarterly={{ ...annual, period: "quarter", rows: [] }}
        valuation={valuation}
        peHistory={{ ticker: "INFY.NS", metric: "pe", points: [], percentile: 62 }}
      />,
    );
    expect(screen.getByText("Year ending")).toBeVisible();
    expect(screen.getByText("USD 20.16B")).toBeVisible();
    expect(screen.getByText("USD 0.78")).toBeVisible();
    expect(screen.getByText("18.0×")).toBeVisible();
    expect(screen.getByText("no dividends reported")).toBeVisible();
    expect(screen.getByText(/Income figures are the last four quarters/)).toBeVisible();
    const note = screen.getByTestId("fundamentals-source").textContent ?? "";
    expect(note).toContain("Not point-in-time");
    expect(note).toContain("Reported in USD; the shares trade in INR");
    expect(screen.getByTestId("pe-percentile").textContent).toContain("62nd percentile");

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Quarterly" }));
  });

  it("says when nothing is stored", () => {
    render(<FundamentalsPanel annual={null} quarterly={null} valuation={null} peHistory={null} />);
    expect(screen.getByTestId("fundamentals-empty")).toBeVisible();
  });
});

describe("ordinal", () => {
  it("handles teens and the usual endings", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 62, 100].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "62nd",
      "100th",
    ]);
  });
});
