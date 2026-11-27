// A9.6: the dividend projection keeps currencies apart and says why a row has none.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DividendProjection } from "@/components/dividend-projection";

describe("DividendProjection", () => {
  it("shows per-currency totals, rows, reasons and the calendar", () => {
    render(
      <DividendProjection
        method="A projection, not a declaration."
        totals={{ USD: "14.64", INR: "250.00" }}
        holdings={[
          {
            ticker: "ACME",
            currency: "USD",
            quantity: "10",
            ttm_per_share: "1.331",
            growth_3y: 0.1,
            growth_used: 0.1,
            next_12m_per_share: "1.4641",
            next_12m_total: "14.64",
            forward_yield: 0.0293,
            streak_years: 2,
            payouts: [{ ex_date: "2027-02-10", per_share: "0.366", amount: "3.66" }],
          },
          {
            ticker: "NOPE",
            currency: "USD",
            quantity: "5",
            ttm_per_share: "0",
            growth_used: 0,
            next_12m_per_share: "0",
            next_12m_total: "0",
            streak_years: 0,
            reason: "No dividend with an ex-date in the last 12 months.",
          },
        ]}
      />,
    );
    const totals = screen.getByTestId("projection-totals");
    expect(totals).toHaveTextContent("USD");
    expect(totals).toHaveTextContent("INR");
    expect(screen.getAllByTestId("projection-row")).toHaveLength(2);
    expect(screen.getByText(/No dividend with an ex-date/)).toBeInTheDocument();
    expect(screen.getByTestId("projection-table")).toHaveTextContent("2.93%");
    expect(screen.getByTestId("projection-calendar")).toHaveTextContent("2027-02-10");
    expect(screen.getByText("A projection, not a declaration.")).toBeInTheDocument();
  });
});
