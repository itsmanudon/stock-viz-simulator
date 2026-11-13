import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioMetrics } from "@/components/portfolio-metrics";
import type { Portfolio } from "@/lib/api/trading";

const base: Portfolio = {
  portfolio_id: 1,
  display_currency: "USD",
  cash_balance: "99200.00",
  reserved_cash: "0",
  available_cash: "97000.00",
  market_value: "0",
  total_value: "99200.00",
  total_cost_basis: "0",
  unrealized_pl: "0",
  options_market_value: "0",
  positions: [],
  option_positions: [],
  valuation_warnings: [],
  cash_by_currency: [],
  base_currency: "USD",
  base_currency_locked: true,
};

describe("PortfolioMetrics other cash (Phase 4.5b)", () => {
  it("shows cash a sale left in another currency, converted and native", () => {
    render(
      <PortfolioMetrics
        portfolio={{
          ...base,
          cash_by_currency: [
            { currency: "USD", amount: "97000", value: "97000" },
            { currency: "EUR", amount: "2000", value: "2200" },
          ],
        }}
        analytics={null}
      />,
    );
    expect(screen.getByText("Other cash")).toBeInTheDocument();
    expect(screen.getByText("$2,200.00")).toBeInTheDocument();
    expect(screen.getByText(/€2,000\.00/)).toBeInTheDocument();
  });

  it("stays hidden for a base-currency-only book and for older responses", () => {
    const { rerender } = render(
      <PortfolioMetrics
        portfolio={{
          ...base,
          cash_by_currency: [{ currency: "USD", amount: "97000", value: "97000" }],
        }}
        analytics={null}
      />,
    );
    expect(screen.queryByText("Other cash")).not.toBeInTheDocument();
    // A response cached before Phase 4.5b has no cash_by_currency at all.
    const older = { ...base, cash_by_currency: undefined } as unknown as Portfolio;
    rerender(<PortfolioMetrics portfolio={older} analytics={null} />);
    expect(screen.queryByText("Other cash")).not.toBeInTheDocument();
  });
});
