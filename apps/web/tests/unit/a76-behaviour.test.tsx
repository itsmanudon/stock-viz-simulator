// A7.6: the behaviour view.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BehaviourView } from "@/components/journal/behaviour-view";
import type { Behaviour } from "@/lib/api/journal-edge";

const b: Behaviour = {
  entries: 32,
  counts_only: false,
  reason: null,
  discipline_scored: 12,
  discipline_followed: 9,
  discipline_rate: 0.75,
  winners: 18,
  losers: 14,
  avg_hold_winners: 2,
  avg_hold_losers: 5,
  disposition_index: 2.5,
  tilt_entries: [41, 57],
  tilt_rate: 0.0625,
  by_weekday: [{ key: "Mon", entries: 7, net_pnl: 120, win_rate: 0.57 }],
  by_hour: [{ key: "10:00", entries: 5, net_pnl: -30, win_rate: 0.4 }],
  fees_total: 84.5,
  fees_per_entry: 2.64,
  fees_share_of_gross: 0.12,
  fees_estimated: true,
  currencies: ["INR"],
  method: {
    discipline: "d",
    disposition_index: "x",
    tilt: "t",
    cost_leakage: "c",
    wording: "Describes the record; not advice",
  },
};

describe("BehaviourView", () => {
  it("shows the figures and links tilt entries", () => {
    render(<BehaviourView behaviour={b} />);
    expect(screen.getByTestId("behaviour-discipline")).toHaveTextContent("9 of 12 (75%)");
    expect(screen.getByTestId("behaviour-disposition")).toHaveTextContent("2.50");
    expect(screen.getByTestId("behaviour-tilt")).toHaveTextContent("2 (6%)");
    expect(screen.getByTestId("behaviour-fees")).toHaveTextContent("12% of gross");
    expect(screen.getByRole("link", { name: "#41" })).toHaveAttribute(
      "href",
      "/portfolio/journal/41",
    );
    expect(screen.getByText(/not advice/)).toBeVisible();
  });
});
