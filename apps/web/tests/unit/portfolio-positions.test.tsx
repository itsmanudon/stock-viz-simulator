import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioEmptyState } from "@/components/portfolio-empty-state";
import { PortfolioPositions } from "@/components/portfolio-positions";
import type { Position } from "@/lib/api/trading";

const foreignPosition: Position = {
  ticker: "7203.T",
  name: "Toyota Motor Corporation",
  quantity: "1000",
  currency: "JPY",
  avg_cost: "2500",
  last_close: "2800",
  market_value_native: "2800000",
  unrealized_pl_native: "300000",
  market_value: "18900",
  unrealized_pl: "2100",
  reserved_quantity: "250",
  available_quantity: "750",
};

describe("portfolio positions", () => {
  it("keeps native price context separate from display-currency value and P&L", () => {
    render(
      <PortfolioPositions
        positions={[foreignPosition]}
        displayCurrency="USD"
        totalValue="128420.38"
      />,
    );

    const table = screen.getByRole("table", { name: "Stock positions" });
    expect(within(table).getByRole("link", { name: "7203.T" })).toHaveAttribute(
      "href",
      "/stocks/7203.T",
    );
    expect(within(table).getByText("Toyota Motor Corporation")).toBeVisible();
    expect(within(table).getByText("¥2,500")).toBeVisible();
    expect(within(table).getByText("¥2,800")).toBeVisible();
    expect(within(table).getByText("$18,900.00")).toBeVisible();
    expect(within(table).getByText("¥2,800,000 native")).toBeVisible();
    expect(within(table).getByText("14.72%")).toBeVisible();
    expect(within(table).getByText("Gain +$2,100.00")).toBeVisible();
    expect(within(table).getByText("+12.50%")).toBeVisible();
  });

  it("shows shares available after reservations and one restrained trade action", () => {
    render(
      <PortfolioPositions
        positions={[foreignPosition]}
        displayCurrency="USD"
        totalValue="128420.38"
      />,
    );

    const table = screen.getByRole("table", { name: "Stock positions" });
    expect(within(table).getByText("750 available")).toBeVisible();
    expect(within(table).getByRole("link", { name: "Trade 7203.T" })).toHaveAttribute(
      "href",
      "/trade?ticker=7203.T",
    );
  });

  it("provides a purpose-built labelled mobile holding row", () => {
    render(
      <PortfolioPositions
        positions={[foreignPosition]}
        displayCurrency="USD"
        totalValue="128420.38"
      />,
    );

    const mobileList = screen.getByRole("list", { name: "Stock positions on mobile" });
    const row = within(mobileList).getByRole("listitem", {
      name: /7203.T Toyota Motor Corporation/,
    });
    expect(within(row).getByText("Market value")).toBeVisible();
    expect(within(row).getByText("1,000 shares · 750 available")).toBeVisible();
    expect(within(row).getByText("Avg ¥2,500 · Last EOD ¥2,800")).toBeVisible();
  });

  it("replaces meaningless zero analytics with a useful new-portfolio state", () => {
    render(<PortfolioEmptyState availableCash="100000" displayCurrency="USD" />);

    expect(screen.getByRole("heading", { name: "Your portfolio is ready" })).toBeVisible();
    expect(screen.getByText(/\$100,000\.00 available to invest/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Explore markets" })).toHaveAttribute(
      "href",
      "/markets",
    );
    expect(screen.getByRole("link", { name: "Place a trade" })).toHaveAttribute("href", "/trade");
    expect(screen.queryByText("Sharpe ratio")).not.toBeInTheDocument();
  });
});
