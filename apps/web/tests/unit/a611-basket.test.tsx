/**
 * A6.11 (M10.5): the basket handoff. CSV and JSON always; Kite's basket form
 * only when the server has KITE_API_KEY (a handoff is passed). Nothing here
 * calls Kite: the form is rendered, never submitted.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const { BasketExport } = await import("@/components/basket-export");
const { basketFromPlan, basketFromRebalance } = await import("@/lib/basket");

const PLAN = {
  ticker: "TCS.NS",
  planned_entry: "3500",
  planned_stop: "3400",
  planned_target: "3800",
  planned_size: "5",
};

describe("BasketExport", () => {
  it("offers CSV and JSON and hides the Kite form without KITE_API_KEY", () => {
    render(<BasketExport orders={basketFromPlan(PLAN)} source="Plan TCS.NS" kite={null} />);
    expect(screen.getByRole("button", { name: /Download CSV/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download JSON/ })).toBeTruthy();
    expect(screen.queryByTestId("basket-kite-form")).toBeNull();
    expect(screen.queryByRole("button", { name: /Review in Kite/ })).toBeNull();
    expect(screen.getByText(/never places an order/)).toBeTruthy();
  });

  it("renders Kite's documented form with the public api_key and the entry only", () => {
    render(
      <BasketExport
        orders={basketFromPlan(PLAN)}
        source="Plan TCS.NS"
        kite={{ apiKey: "publicappkey", url: "https://kite.zerodha.com/connect/basket" }}
      />,
    );
    const form = screen.getByTestId("basket-kite-form") as HTMLFormElement;
    expect(form.getAttribute("action")).toBe("https://kite.zerodha.com/connect/basket");
    expect(form.getAttribute("method")).toBe("post");
    const fields = Object.fromEntries(
      Array.from(form.querySelectorAll("input")).map((i) => [i.name, i.value]),
    );
    expect(Object.keys(fields)).toEqual(["api_key", "data"]);
    expect(fields.api_key).toBe("publicappkey");
    const data = JSON.parse(fields.data ?? "[]");
    expect(data).toHaveLength(1);
    expect(data[0]).toMatchObject({ tradingsymbol: "TCS", transaction_type: "BUY", quantity: 5 });
    expect(screen.getByText(/entry only/)).toBeTruthy();
  });

  it("offers no Kite form for a US-only basket, and nothing for an empty one", () => {
    const kite = { apiKey: "k", url: "https://kite.zerodha.com/connect/basket" };
    const { rerender } = render(
      <BasketExport
        orders={basketFromRebalance([{ ticker: "AAPL", side: "buy", quantity: 2 }])}
        source="Rebalance"
        kite={kite}
      />,
    );
    expect(screen.queryByTestId("basket-kite-form")).toBeNull();
    rerender(<BasketExport orders={[]} source="Rebalance" kite={kite} />);
    expect(screen.queryByTestId("basket-export")).toBeNull();
  });
});
