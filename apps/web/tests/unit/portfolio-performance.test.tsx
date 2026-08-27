import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EquityCurve } from "@/components/equity-curve";
import { PortfolioMetrics } from "@/components/portfolio-metrics";
import { PortfolioPerformance } from "@/components/portfolio-performance";
import type { Portfolio, PortfolioAnalytics } from "@/lib/api/trading";

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

vi.mock("lightweight-charts", () => ({
  AreaSeries: "AreaSeries",
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

const portfolio: Portfolio = {
  portfolio_id: 1,
  display_currency: "EUR",
  cash_balance: "23402.00",
  reserved_cash: "402.00",
  available_cash: "23000.00",
  market_value: "100018.38",
  total_value: "128420.38",
  total_cost_basis: "90000.00",
  unrealized_pl: "10018.38",
  options_market_value: "5000.00",
  positions: [
    {
      ticker: "SAP",
      name: "SAP SE",
      quantity: "10",
      currency: "EUR",
      avg_cost: "180",
      last_close: "200",
      market_value_native: "2000",
      unrealized_pl_native: "200",
      market_value: "2000",
      unrealized_pl: "200",
      reserved_quantity: "0",
      available_quantity: "10",
    },
  ],
  option_positions: [],
};

const analytics: PortfolioAnalytics = {
  display_currency: "EUR",
  history_days: 240,
  total_return_pct: 28.42,
  annualised_return_pct: 14.11,
  sharpe_ratio: 1.36,
  max_drawdown_pct: -8.725,
  risk_free_rate: 0.05,
  sector_allocation: [],
  top_gainers: [],
  top_losers: [],
};

describe("portfolio performance hierarchy", () => {
  it("makes current display-currency value primary while labelling historical change as USD NAV", () => {
    render(
      <PortfolioPerformance
        portfolio={portfolio}
        history={[
          { date: "2026-06-01", nav: "126236.18" },
          { date: "2026-08-27", nav: "128420.38" },
        ]}
        range="3m"
        tab="positions"
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Portfolio" })).toBeVisible();
    expect(screen.getByText("€128,420.38")).toBeVisible();
    expect(screen.getByText("3M USD NAV change")).toBeVisible();
    expect(screen.getByText("+$2,184.20")).toBeVisible();
    expect(screen.getByText("+1.73%")).toBeVisible();
    expect(screen.getByText(/Latest EOD valuation/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Trade" })).toHaveAttribute("href", "/trade");
    expect(screen.getByRole("link", { name: "3M" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: "1Y" })).toHaveAttribute(
      "href",
      "/portfolio?range=1y",
    );
  });

  it("distinguishes unavailable history from insufficient successful history", () => {
    const { rerender } = render(
      <PortfolioPerformance
        portfolio={portfolio}
        history={null}
        range="3m"
        tab="orders"
      />,
    );
    expect(screen.getByText("Performance history is temporarily unavailable.")).toBeVisible();

    rerender(
      <PortfolioPerformance
        portfolio={portfolio}
        history={[{ date: "2026-08-27", nav: "128420.38" }]}
        range="3m"
        tab="orders"
      />,
    );
    expect(screen.getByText(/Performance appears after two daily snapshots/)).toBeVisible();
    expect(screen.getByRole("link", { name: "1Y" })).toHaveAttribute(
      "href",
      "/portfolio?range=1y&tab=orders",
    );
  });

  it("presents current balances and all-history risk metrics as one compact ledger", () => {
    render(<PortfolioMetrics portfolio={portfolio} analytics={analytics} />);

    expect(screen.getByText("Available cash")).toBeVisible();
    expect(screen.getByText("€23,000.00")).toBeVisible();
    expect(screen.getByText("Invested equities")).toBeVisible();
    expect(screen.getByText("€100,018.38")).toBeVisible();
    expect(screen.getByText("Options exposure")).toBeVisible();
    expect(screen.getByText("All-history return")).toBeVisible();
    expect(screen.getByText("+28.42%")).toBeVisible();
    expect(screen.getByText("1.36")).toBeVisible();
    expect(screen.getByText("-8.73%")).toBeVisible();
    expect(screen.getByText(/Based on 240 daily snapshots/)).toBeVisible();
  });

  it("suppresses meaningless risk cells for a new portfolio", () => {
    render(
      <PortfolioMetrics
        portfolio={{
          ...portfolio,
          market_value: "0",
          options_market_value: "0",
          positions: [],
          option_positions: [],
        }}
        analytics={{
          ...analytics,
          history_days: 0,
          total_return_pct: null,
          annualised_return_pct: null,
          sharpe_ratio: null,
          max_drawdown_pct: null,
        }}
      />,
    );

    expect(screen.getByText("Available cash")).toBeVisible();
    expect(screen.queryByText("Sharpe ratio")).not.toBeInTheDocument();
    expect(screen.queryByText("Max drawdown")).not.toBeInTheDocument();
    expect(screen.queryByText("Options exposure")).not.toBeInTheDocument();
  });

  it("provides a textual equivalent for the canvas chart", () => {
    render(
      <EquityCurve
        points={[
          { date: "2026-06-01", nav: "100000" },
          { date: "2026-08-27", nav: "112500" },
        ]}
        accessibleLabel="3M USD NAV chart, up 12.50% from June 1 to August 27."
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "3M USD NAV chart, up 12.50% from June 1 to August 27.",
      }),
    ).toBeVisible();
  });
});
