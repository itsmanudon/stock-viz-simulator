/** A9.13 (M8.5): implied vs model distribution card. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImpliedDistributionCard, densityPath } from "@/components/implied-distribution-card";
import type { ImpliedDistribution } from "@/lib/api/option-exposure";

const data: ImpliedDistribution = {
  ticker: "AAPL",
  expiry: "2026-12-04",
  days: 7,
  spot: 355.58,
  implied_atm_vol: 0.2836,
  model_vol: 0.2948,
  model_vol_source: "HAR-RV forecast (A9.2)",
  quantile_levels: [0.05, 0.25, 0.5, 0.75, 0.95],
  implied_quantiles: [322.84, 347.36, 357.16, 365.44, 376.27],
  model_quantiles: [332.53, 345.97, 355.62, 365.55, 380.32],
  move: 0.1,
  implied_p_down: 0.0375,
  implied_p_up: 0.0015,
  model_p_down: 0.0046,
  model_p_up: 0.01,
  negative_mass: 0.0321,
  strikes_used: 27,
  curve: [
    { price: 300, implied: 0, model: 0 },
    { price: 355, implied: 0.02, model: 0.025 },
    { price: 410, implied: 0, model: 0 },
  ],
  reason: null,
  method: "Breeden-Litzenberger. Includes the market's risk premium.",
};

describe("implied distribution card", () => {
  it("draws both densities on one scale", () => {
    expect(densityPath(data.curve, "model")).toBe("M0.0,120.0 L160.0,0.0 L320.0,120.0");
    expect(densityPath(data.curve, "implied")).toBe("M0.0,120.0 L160.0,24.0 L320.0,120.0");
    expect(densityPath([], "implied")).toBe("");
  });

  it("writes every figure as text", () => {
    render(<ImpliedDistributionCard data={data} />);
    expect(screen.getByText(/Implied ATM volatility 28.4%; model 29.5%/)).toBeInTheDocument();
    expect(screen.getByTestId("idist-tails")).toHaveTextContent(
      "more than 10% below spot: implied 3.8%, model 0.5%; above: implied 0.1%, model 1.0%.",
    );
    expect(screen.getByTestId("idist-quantiles")).toHaveTextContent("322.84");
    expect(screen.getByText(/3.2% of the raw density was negative/)).toBeInTheDocument();
  });
});
