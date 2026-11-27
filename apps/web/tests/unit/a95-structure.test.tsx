// A9.5: structure annotations state their rules.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StructureView } from "@/components/structure-view";
import type { Structure } from "@/lib/api/research-views";

const structure: Structure = {
  ticker: "ACME",
  n: 5,
  sessions: 250,
  atr: 2,
  pivots: [
    { day: "2026-10-01", kind: "high", price: 110, label: null, confirmed_at: "2026-10-08" },
    { day: "2026-10-20", kind: "high", price: 112, label: "HH", confirmed_at: "2026-10-27" },
  ],
  zones: [
    { low: 99, high: 100, touches: 3, side: "support", first: "2026-06-01", last: "2026-09-01" },
  ],
  rules: { pivot: "A swing high tops the 5 bars before it", zones: "Pivots within ATR(14) / 2" },
};

describe("StructureView", () => {
  it("shows zones, labelled pivots and the rules", () => {
    render(<StructureView structure={structure} />);
    expect(screen.getByTestId("structure-zones")).toHaveTextContent("Support");
    expect(screen.getByTestId("structure-zones")).toHaveTextContent("3 touches");
    expect(screen.getByTestId("structure-pivots")).toHaveTextContent("HH");
    expect(screen.getByText(/Pivots within ATR\(14\) \/ 2/)).toBeInTheDocument();
  });

  it("says when there is no zone", () => {
    render(<StructureView structure={{ ...structure, zones: [] }} />);
    expect(screen.getByText(/No zone with two or more/)).toBeInTheDocument();
  });
});
