import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axisFormatter } from "@/components/equity-curve";
import { goalOdds } from "@/components/portfolio-risk";
import { RebalancePreview, rebalanceLines } from "@/components/rebalance-preview";
import type { Position } from "@/lib/api/trading";

const positions = [
  { ticker: "AAPL", quantity: "100", market_value: "15000" }, // 150 a share
  { ticker: "KO", quantity: "50", market_value: "3000" }, // 60 a share
] as Position[];

describe("Phase 8.6 small items", () => {
  it("rebalances in whole shares at today's value", () => {
    // NAV 100,000: AAPL 15% -> 10% sells 33 (5,000 / 150 = 33.3); KO 3% -> 5% buys 33.
    const lines = rebalanceLines(positions, { AAPL: 10, KO: 5 }, 100_000);
    expect(lines).toEqual([
      { ticker: "AAPL", side: "sell", quantity: 33, amount: 4950 },
      { ticker: "KO", side: "buy", quantity: 33, amount: 1980 },
    ]);
    expect(rebalanceLines(positions, { AAPL: 15, KO: 3 }, 100_000)).toEqual([]);
  });

  it("previews orders as the targets change and places nothing", () => {
    render(<RebalancePreview positions={positions} nav={100_000} currency="USD" />);
    expect(screen.getByText(/no whole share needs to move/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("AAPL"), { target: { value: "10" } });
    const orders = screen.getByRole("list", { name: "Orders to reach the targets" });
    expect(within(orders).getByText(/Sell 33/)).toBeTruthy();
    expect(within(orders).getByRole("link", { name: "Open ticket" }).getAttribute("href")).toBe(
      "/trade?ticker=AAPL",
    );
  });

  it("formats the NAV axis in the account's currency (UX-9)", () => {
    expect(axisFormatter("USD")(106000)).toBe("$106,000");
    expect(axisFormatter("INR")(10000000)).toBe("₹10,000,000");
  });

  it("puts a goal's chance in words", () => {
    expect(goalOdds(0.25)).toBe("about 1 in 4");
    expect(goalOdds(0.62)).toBe("about 62 in 100");
    expect(goalOdds(0.999)).toBe("nearly every path");
    expect(goalOdds(0.001)).toBe("almost no path");
  });
});
