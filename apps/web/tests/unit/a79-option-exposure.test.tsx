// A7.9: the exposure card and the payoff chart's what-if curve.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptionExposureCard } from "@/components/option-exposure-card";
import { PayoffChart } from "@/components/payoff-chart";
import type { OptionExposure } from "@/lib/api/option-exposure";

const exposure: OptionExposure = {
  ticker: "ACME",
  snapshot_date: "2026-11-20",
  spot: 100,
  expiries: ["2026-12-18"],
  strikes: [
    { strike: 90, gex: -2_000_000, dex: -1, call_oi: 0, put_oi: 5000 },
    { strike: 110, gex: 3_000_000, dex: 1, call_oi: 6000, put_oi: 0 },
  ],
  total_gex: 1_000_000,
  total_dex: 0,
  gamma_flip: 98.5,
  call_wall: 110,
  put_wall: 90,
  expected_move_1d: 1.89,
  atm_iv: 0.3,
  used: 4,
  skipped: 1,
  reason: null,
  note: "Volatility-regime context, not direction.",
};

describe("OptionExposureCard", () => {
  it("shows the key levels", () => {
    render(<OptionExposureCard exposure={exposure} />);
    expect(screen.getByTestId("exposure-flip")).toHaveTextContent("98.50");
    expect(screen.getByTestId("exposure-walls")).toHaveTextContent("110.00 / 90.00");
    expect(screen.getByTestId("exposure-move")).toHaveTextContent("±1.89");
    expect(screen.getByText(/not direction/)).toBeVisible();
  });
});

describe("PayoffChart what-if", () => {
  const points = [
    { spot: 90, at_expiry: -100, today: -50 },
    { spot: 110, at_expiry: 100, today: 50 },
  ];
  it("draws the what-if curve only when given", () => {
    const { container, rerender } = render(
      <PayoffChart points={points} spot={100} breakevens={[]} horizon="2026-12-18" />,
    );
    expect(container.querySelector('[data-testid="payoff-what-if"]')).toBeNull();
    rerender(
      <PayoffChart
        points={points.map((p) => ({ ...p, what_if: p.today - 20 }))}
        spot={100}
        breakevens={[]}
        horizon="2026-12-18"
      />,
    );
    expect(container.querySelector('[data-testid="payoff-what-if"]')).not.toBeNull();
    expect(screen.getByText("Dotted: what-if")).toBeVisible();
  });
});
