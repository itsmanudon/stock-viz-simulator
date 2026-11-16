import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioStressPanel } from "@/components/portfolio-stress";
import type { PortfolioStress } from "@/lib/api/trading";

const stress: PortfolioStress = {
  currency: "USD",
  method: "instant_revaluation",
  basis: "each scenario applied instantly to today's holdings in the base currency",
  scenarios: [
    {
      key: "covid_2020",
      name: "COVID crash",
      kind: "historical",
      start: "2020-02-19",
      end: "2020-03-23",
      nav_before: 100000,
      nav_after: 96200,
      change: -3800,
      change_pct: -3.8,
      drivers: [{ ticker: "MSFT", change: -2400 }],
      proxied: ["MSFT"],
      missing: ["NEW"],
    },
    {
      key: "combined",
      name: "US -20%, India -20%, rupee 10% weaker",
      kind: "hypothetical",
      start: null,
      end: null,
      nav_before: 100000,
      nav_after: 96485.6,
      change: -3514.4,
      change_pct: -3.5144,
      drivers: [{ ticker: "AAPL", change: -2000 }],
      proxied: [],
      missing: [],
    },
  ],
};

describe("PortfolioStressPanel (Phase 8.4)", () => {
  it("separates past crises from fixed shocks and says what was proxied", () => {
    render(<PortfolioStressPanel stress={stress} open />);
    expect(screen.getByText(/Method: each scenario applied instantly/)).toBeTruthy();
    const past = screen.getByRole("table", { name: "Past crises" });
    expect(within(past).getByText("Feb 19, 2020 to Mar 23, 2020")).toBeTruthy();
    expect(within(past).getByText(/Index and beta used for MSFT/)).toBeTruthy();
    expect(within(past).getByText(/No history, left unmoved: NEW/)).toBeTruthy();
    const shocks = screen.getByRole("table", { name: "Fixed shocks" });
    expect(within(shocks).getByText("-$3,514.40")).toBeTruthy();
  });

  it("renders nothing off the Analytics tab", () => {
    const { container } = render(<PortfolioStressPanel stress={stress} open={false} />);
    expect(container.textContent).toBe("");
  });
});
