// A9.4: the volatility summary card.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VolSummaryCard } from "@/components/vol-summary-card";
import type { VolSummary } from "@/lib/api/option-exposure";

const summary: VolSummary = {
  ticker: "ACME",
  snapshot_date: "2026-11-20",
  spot: 100,
  term: [
    { expiry: "2026-12-18", days: 28, atm_iv: 0.3, skew_25d: 0.04 },
    { expiry: "2027-02-18", days: 90, atm_iv: 0.32, skew_25d: 0.03 },
  ],
  atm_30d: 0.3,
  realised_21d: 0.22,
  vrp: 0.08,
  iv_rank: null,
  iv_percentile: null,
  snapshots: 6,
  reason: null,
  method: "Context, not a signal on its own.",
};

describe("VolSummaryCard", () => {
  it("shows VRP, the term structure and why IV rank is missing", () => {
    render(<VolSummaryCard summary={summary} />);
    expect(screen.getByTestId("vol-vrp")).toHaveTextContent("+8.0 pts");
    expect(screen.getByTestId("vol-rank")).toHaveTextContent("needs 20 snapshots (6)");
    expect(screen.getByTestId("vol-term")).toHaveTextContent("32.0%");
  });

  it("shows IV rank when there is history", () => {
    render(
      <VolSummaryCard summary={{ ...summary, iv_rank: 0.25, iv_percentile: 0.4, snapshots: 40 }} />,
    );
    expect(screen.getByTestId("vol-rank")).toHaveTextContent("25 / 40");
  });
});
