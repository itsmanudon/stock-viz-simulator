import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioMetrics } from "@/components/portfolio-metrics";
import { PortfolioReturnsPanel } from "@/components/portfolio-returns";
import type { Portfolio, PortfolioReturns } from "@/lib/api/trading";

const returns: PortfolioReturns = {
  currency: "USD",
  twr_method: "time_weighted",
  twr_basis: "opening value, nightly NAV snapshots and the live valuation, chained",
  periods: [
    {
      period: "1M",
      start_date: "2026-10-13",
      end_date: "2026-11-13",
      return_pct: 1.5,
      annualised_pct: null,
    },
    {
      period: "1Y",
      start_date: null,
      end_date: "2026-11-13",
      return_pct: null,
      annualised_pct: null,
      reason: "account is younger than the period",
    },
  ],
  xirr_method: "money_weighted_xirr",
  xirr_basis: "dated cash flows in the base currency, today's value as the last flow",
  account_xirr: { rate_pct: 18.25, first_flow: "2026-05-01", flows: 2 },
  holdings: [
    {
      ticker: "MSFT",
      kind: "equity",
      xirr: { rate_pct: -17.5, first_flow: "2026-05-01", flows: 2 },
    },
    {
      ticker: "OPTIONS",
      kind: "options",
      xirr: { rate_pct: null, first_flow: "2026-11-01", flows: 1, reason: "held under 30 days" },
    },
  ],
};

describe("PortfolioReturnsPanel (Phase 8.1)", () => {
  it("names each method beside its figures and says why a figure is missing", () => {
    render(<PortfolioReturnsPanel returns={returns} />);
    expect(screen.getByText(/Method: time-weighted/)).toBeTruthy();
    expect(screen.getByText(/Method: XIRR/)).toBeTruthy();
    const twr = screen.getByRole("table", { name: "Time-weighted return by period" });
    expect(within(twr).getByText("+1.50%")).toBeTruthy();
    expect(within(twr).getByText("account is younger than the period")).toBeTruthy();
    const xirr = screen.getByRole("table", { name: "Money-weighted return by holding" });
    expect(within(xirr).getByText("Whole account")).toBeTruthy();
    expect(within(xirr).getByText("-17.50%")).toBeTruthy();
    expect(within(xirr).getByText("Options book")).toBeTruthy();
    expect(within(xirr).getByText("held under 30 days")).toBeTruthy();
  });

  it("says so when returns are unavailable", () => {
    render(<PortfolioReturnsPanel returns={null} />);
    expect(screen.getByText(/Returns are unavailable/)).toBeTruthy();
  });
});

const portfolio: Portfolio = {
  portfolio_id: 1,
  display_currency: "USD",
  cash_balance: "90000",
  reserved_cash: "0",
  available_cash: "90000",
  market_value: "900",
  total_value: "91100",
  total_cost_basis: "1000",
  unrealized_pl: "100",
  unrealized_pl_equity: "-100",
  unrealized_pl_options: "200",
  realized_pl: "400",
  realized_pl_unavailable: 1,
  options_market_value: "300",
  positions: [],
  option_positions: [
    {
      option_id: 1,
      ticker: "AAPL",
      option_type: "call",
      strike: "140",
      expiry: "2026-12-18",
      quantity: 1,
      currency: "USD",
      premium_paid: "100",
      market_value_native: "300",
      market_value: "300",
      unrealized_pl: "200",
    },
  ],
  valuation_warnings: [],
  cash_by_currency: [],
  base_currency: "USD",
  base_currency_locked: true,
};

describe("PortfolioMetrics P&L (#68)", () => {
  it("shows open P&L with options and lifetime realized P&L", () => {
    render(<PortfolioMetrics portfolio={portfolio} analytics={null} />);
    expect(screen.getByText("Unrealized P&L")).toBeTruthy();
    expect(screen.getByText(/Equities -\$100\.00 · options \+\$200\.00/)).toBeTruthy();
    expect(screen.getByText("Realized P&L")).toBeTruthy();
    expect(screen.getByText(/1 close with no recorded figure left out/)).toBeTruthy();
  });
});
