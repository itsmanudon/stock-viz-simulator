// A7.4: the reverse DCF card shows the implied growth, the grid and the reconciliation.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type ReverseDcf, ReverseDcfCard } from "@/components/reverse-dcf-card";

const data: ReverseDcf = {
  ticker: "INFY.NS",
  as_of: "2026-11-10",
  currency: "USD",
  implied_growth: 0.0842,
  reason: null,
  base_fcf: 4000,
  base_fcf_source: "trailing free cash flow",
  wacc: 0.09,
  terminal_growth: 0.03,
  years: 10,
  enterprise_value: 80000,
  sensitivity: [
    { wacc: 0.08, terminal_growth: 0.03, implied_growth: 0.06 },
    { wacc: 0.09, terminal_growth: 0.03, implied_growth: 0.0842 },
  ],
  reconciliation: [
    { step: "enterprise_value", value: 80000 },
    { step: "price", value: 18 },
  ],
  method: "Two-stage DCF.",
};

describe("ReverseDcfCard", () => {
  it("states the implied growth and its inputs", () => {
    render(<ReverseDcfCard ticker="INFY.NS" initial={data} />);
    expect(screen.getByTestId("reverse-dcf-result")).toHaveTextContent("8.4%");
    expect(screen.getByTestId("reverse-dcf-result")).toHaveTextContent("10 years");
    expect(screen.getByTestId("reverse-dcf-grid")).toHaveTextContent("6.0%");
    expect(screen.getByText(/Price 18.00/)).toBeVisible();
  });

  it("gives the reason when nothing solves", () => {
    render(
      <ReverseDcfCard
        ticker="X"
        initial={{
          ...data,
          implied_growth: null,
          reason: "Free cash flow is not positive.",
          sensitivity: [],
        }}
      />,
    );
    expect(screen.getByTestId("reverse-dcf-result")).toHaveTextContent("not positive");
    expect(screen.queryByTestId("reverse-dcf-grid")).toBeNull();
  });
});
