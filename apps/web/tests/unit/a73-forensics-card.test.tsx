// A7.3: the forensic scorecard card.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ForensicsCard } from "@/components/forensics-card";
import type { Forensics } from "@/lib/api/fundamentals";

const base: Forensics = {
  ticker: "ACME",
  as_of: "2026-11-27",
  sector: "Technology",
  financial: false,
  financial_note: null,
  fiscal_year_end: "2025-12-31",
  previous_year_end: "2024-12-31",
  currency: "USD",
  piotroski_score: 7,
  piotroski_known: 8,
  piotroski: [
    { key: "roa", label: "Return on assets above 0", result: "pass", detail: "x" },
    { key: "delta_margin", label: "Gross margin up", result: "unknown", detail: "y" },
  ],
  altman_z: { value: 7.57, zone: "safe", missing: [], parts: {} },
  beneish_m: { value: null, zone: null, missing: ["sga"], parts: {} },
  cfo_to_pat: { value: 1.25, zone: "strong", missing: [], parts: {} },
  reason: null,
  method: { altman_z: "a", beneish_m: "b", cfo_to_pat: "c", point_in_time: "As filed." },
};

describe("ForensicsCard", () => {
  it("shows the scores and names what is missing", () => {
    render(<ForensicsCard forensics={base} />);
    expect(screen.getByTestId("forensics-piotroski")).toHaveTextContent("7 of 8 known");
    const card = screen.getByTestId("forensics-card");
    expect(card).toHaveTextContent("7.57");
    expect(card).toHaveTextContent("Safe zone");
    expect(card).toHaveTextContent("Unknown: no sga");
    expect(card).toHaveTextContent("Cash above profit");
  });

  it("switches off for a financial company", () => {
    render(
      <ForensicsCard
        forensics={{ ...base, financial: true, financial_note: "A financial company." }}
      />,
    );
    expect(screen.getByTestId("forensics-financial")).toHaveTextContent("A financial company.");
    expect(screen.queryByTestId("forensics-piotroski")).toBeNull();
  });
});
