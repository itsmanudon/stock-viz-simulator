import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MobileTradeSheet } from "@/components/mobile-trade-sheet";

vi.mock("@/app/(product)/(authed)/trade/actions", () => ({
  placeTradeAction: vi.fn().mockResolvedValue({}),
  placeOrderAction: vi.fn().mockResolvedValue({}),
}));

describe("MobileTradeSheet", () => {
  it("opens with the requested side and closes through the labelled control", () => {
    render(
      <MobileTradeSheet
        ticker="AAPL"
        name="Apple Inc."
        currency="USD"
        latestClose={25}
        callbackUrl="/stocks/AAPL?tf=1Y&indicators=sma_50"
        signedIn
        account={{ displayCurrency: "USD", availableCash: 100, position: null }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sell AAPL" }));
    expect(screen.getByRole("dialog", { name: "Paper trade AAPL" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Sell", pressed: true })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Close paper trade" }));
    expect(screen.queryByRole("dialog", { name: "Paper trade AAPL" })).not.toBeInTheDocument();
  });
});
