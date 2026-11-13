import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioAttributionPanel, PortfolioExposurePanel } from "@/components/portfolio-exposure";
import type { PortfolioAttribution, PortfolioExposure } from "@/lib/api/trading";

const exposure: PortfolioExposure = {
  currency: "USD",
  method: "share_of_nav",
  basis: "equities at market value and cash by currency, as a share of NAV",
  dimensions: [
    {
      dimension: "currency",
      buckets: [
        {
          key: "USD",
          equity_value: "1500",
          cash_value: "8000",
          options_delta: "640",
          weight_pct: 88.3,
          options_delta_pct: 5.9,
        },
        {
          key: "EUR",
          equity_value: "1260",
          cash_value: "0",
          options_delta: "0",
          weight_pct: 11.7,
          options_delta_pct: 0,
        },
      ],
    },
  ],
};

const attribution: PortfolioAttribution = {
  currency: "USD",
  method: "price_currency_cross",
  basis: "gain since entry in the base currency",
  holdings: [
    {
      ticker: "SAP.DE",
      currency: "EUR",
      entry_rate: "1.10",
      rate_now: "1.05",
      cost_base: "1100",
      value_base: "1260",
      price_effect: "220",
      currency_effect: "-50",
      cross_effect: "-10",
      income: "0",
    },
    {
      ticker: "7203.T",
      currency: "JPY",
      entry_rate: null,
      rate_now: null,
      cost_base: null,
      value_base: null,
      price_effect: null,
      currency_effect: null,
      cross_effect: null,
      income: "0",
      reason: "a buy has no stored rate",
    },
  ],
};

describe("Exposure and attribution panels (Phase 8.2)", () => {
  it("weights each bucket and keeps options delta beside the weight", () => {
    render(<PortfolioExposurePanel exposure={exposure} />);
    expect(screen.getByText(/Method: equities at market value/)).toBeTruthy();
    const list = screen.getByRole("list", { name: "By currency" });
    expect(within(list).getByText("88.3%")).toBeTruthy();
    expect(within(list).getByText(/Options: \+\$640\.00 delta \(5\.9% of NAV\)/)).toBeTruthy();
  });

  it("splits a foreign holding's gain and explains a missing split", () => {
    render(<PortfolioAttributionPanel attribution={attribution} />);
    const table = screen.getByRole("table", { name: "Gain by source" });
    expect(within(table).getByText("+$220.00")).toBeTruthy();
    expect(within(table).getByText("-$50.00")).toBeTruthy();
    expect(within(table).getByText("a buy has no stored rate")).toBeTruthy();
  });
});
