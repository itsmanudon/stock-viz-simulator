import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioInsights } from "@/components/portfolio-analytics";
import type { PortfolioAnalytics } from "@/lib/api/trading";

const analytics: PortfolioAnalytics = {
  display_currency: "USD",
  history_days: 240,
  total_return_pct: 28.42,
  annualised_return_pct: 14.11,
  sharpe_ratio: 1.36,
  max_drawdown_pct: -8.72,
  risk_free_rate: 0.05,
  sector_allocation: [
    { sector: "Technology", market_value: "42700", pct: 42.7 },
    { sector: "Financials", market_value: "21300", pct: 21.3 },
  ],
  top_gainers: [
    {
      ticker: "NVDA",
      name: "NVIDIA Corporation",
      sector: "Technology",
      unrealized_pl: "4180",
      return_pct: 18.2,
    },
  ],
  top_losers: [
    {
      ticker: "DIS",
      name: "The Walt Disney Company",
      sector: "Communication Services",
      unrealized_pl: "-640",
      return_pct: -6.4,
    },
  ],
};

describe("portfolio insights", () => {
  it("labels equity-only exposure and position movers without claiming attribution", () => {
    render(<PortfolioInsights analytics={analytics} hasEquityPositions />);

    expect(screen.getByRole("heading", { name: "Equity sector allocation" })).toBeVisible();
    expect(screen.getByText("Cash and options excluded")).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: "Equity sector allocation: Technology 42.7%, Financials 21.3%",
      }),
    ).toBeVisible();
    expect(screen.getByText("Technology")).toBeVisible();
    expect(screen.getByText("42.7%")).toBeVisible();

    const movers = screen.getByRole("region", { name: "Top movers" });
    expect(within(movers).getByText("Gainers")).toBeVisible();
    expect(within(movers).getByText("Detractors")).toBeVisible();
    expect(within(movers).getByRole("link", { name: "NVDA" })).toHaveAttribute(
      "href",
      "/stocks/NVDA",
    );
    expect(within(movers).getByText("Gain +$4,180.00")).toBeVisible();
    expect(within(movers).getByText("Loss -$640.00")).toBeVisible();
    expect(screen.queryByText(/contributor/i)).not.toBeInTheDocument();
  });

  it("distinguishes unavailable insight data from a portfolio without equities", () => {
    const { rerender, container } = render(
      <PortfolioInsights analytics={null} hasEquityPositions />,
    );
    expect(screen.getByText("Portfolio insights are temporarily unavailable.")).toBeVisible();

    rerender(<PortfolioInsights analytics={analytics} hasEquityPositions={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
