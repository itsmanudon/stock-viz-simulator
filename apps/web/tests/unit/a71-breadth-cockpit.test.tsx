// A7.1: the breadth cockpit renders each market's latest figures.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BreadthCockpit } from "@/components/breadth-cockpit";
import type { Breadth } from "@/lib/api/breadth";

const point = (date: string, adv: number, dec: number, extra = {}) => ({
  date,
  advancers: adv,
  decliners: dec,
  unchanged: 0,
  members: adv + dec,
  new_highs: 2,
  new_lows: 1,
  highs_minus_lows: 1,
  ad_line: adv - dec,
  ad_ratio_20: 1.25,
  ad_ratio_40: 1.1,
  mcclellan: 12.5,
  summation: 40,
  thrust_ema10: 0.5,
  thrust: false,
  pct_above_20: 55,
  pct_above_50: 61.2,
  pct_above_100: 50,
  pct_above_200: 47.9,
  pct_rsi_50: 52,
  ...extra,
});

const us: Breadth = {
  market: "US",
  start: "2026-01-01",
  end: "2026-01-07",
  members: 25,
  universe_note: "Active symbols stored today (survivorship-biased).",
  method: { mcclellan: "EMA19 - EMA39", ad_ratio: "x", new_highs: "y", pct_above_sma: "z" },
  points: [point("2026-01-06", 10, 15, { thrust: true }), point("2026-01-07", 18, 7)],
};

describe("BreadthCockpit", () => {
  it("shows the latest session and the last thrust", () => {
    render(<BreadthCockpit markets={[us]} />);
    const panel = screen.getByTestId("breadth-US");
    expect(panel).toHaveTextContent("2026-01-07 · 25 members");
    expect(panel).toHaveTextContent("18 / 25");
    expect(panel).toHaveTextContent("12.5");
    expect(panel).toHaveTextContent("61%");
    expect(panel).toHaveTextContent("Last breadth thrust: 2026-01-06.");
    expect(screen.getByText(/survivorship-biased/)).toBeVisible();
  });

  it("renders nothing without markets", () => {
    const { container } = render(<BreadthCockpit markets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
