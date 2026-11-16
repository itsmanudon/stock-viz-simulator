import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioRiskPanel } from "@/components/portfolio-risk";
import type { PortfolioRisk } from "@/lib/api/trading";

const risk: PortfolioRisk = {
  currency: "USD",
  nav: 100000,
  method: "historical_simulation",
  var_rule: "VaR is the k-th worst scenario loss",
  window: { start: "2024-11-15", end: "2026-11-12", sessions: 500 },
  holdings_included: 2,
  excluded: [{ ticker: "7203.T", reason: "no FX history for its currency" }],
  proxied: [{ ticker: "RELIANCE.NS", proxy: "^NSEI", days: 40 }],
  var: [
    {
      confidence: 0.95,
      horizon_days: 1,
      scenarios: 500,
      tail_count: 25,
      var: 1830.5,
      var_pct: 1.8305,
      cvar: 2650,
      cvar_pct: 2.65,
    },
  ],
  monte_carlo: {
    method: "stationary_block_bootstrap",
    paths: 10000,
    horizon_days: 252,
    mean_block: 5,
    seed: 1,
    percentiles: { "5": 81000, "25": 95000, "50": 106000, "75": 117000, "95": 134000 },
    prob_loss_10: 0.081,
    prob_loss_20: 0.02,
  },
};

describe("PortfolioRiskPanel (Phase 8.3)", () => {
  it("states method, window and tail beside every figure", () => {
    render(<PortfolioRiskPanel risk={risk} open />);
    expect(screen.getByText(/historical simulation of today's holdings over 500/)).toBeTruthy();
    const table = screen.getByRole("table", { name: "Value at risk" });
    expect(within(table).getByText("$1,830.50")).toBeTruthy();
    expect(within(table).getByText("worst 25 of 500")).toBeTruthy();
    expect(screen.getByText(/stationary block bootstrap/)).toBeTruthy();
    expect(screen.getByText(/more than 10%: 8\.1%/)).toBeTruthy();
    expect(screen.getByText(/RELIANCE\.NS: 40 early sessions use \^NSEI/)).toBeTruthy();
    expect(screen.getByText(/7203\.T left out/)).toBeTruthy();
  });

  it("explains a missing report and stays hidden off the tab", () => {
    const { container, rerender } = render(<PortfolioRiskPanel risk={null} open={false} />);
    expect(container.textContent).toBe("");
    rerender(
      <PortfolioRiskPanel
        risk={{
          ...risk,
          var: [],
          monte_carlo: null,
          reason: "38 sessions of history; 250 are needed",
        }}
        open
      />,
    );
    expect(screen.getByText(/No risk figures yet: 38 sessions/)).toBeTruthy();
  });
});
