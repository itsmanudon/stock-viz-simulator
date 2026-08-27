import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContextualTradeTicket } from "@/components/contextual-trade-ticket";

vi.mock("@/app/(product)/(authed)/trade/actions", () => ({
  placeTradeAction: vi.fn().mockResolvedValue({}),
  placeOrderAction: vi.fn().mockResolvedValue({}),
}));

const baseProps = {
  ticker: "AAPL",
  name: "Apple Inc.",
  currency: "USD",
  latestClose: 25,
  callbackUrl: "/stocks/AAPL?tf=1Y&indicators=sma_50",
};

const account = {
  displayCurrency: "USD",
  availableCash: 100,
  position: null,
};

describe("ContextualTradeTicket", () => {
  it("keeps guest research open and offers a route-aware sign-in action", () => {
    render(<ContextualTradeTicket {...baseProps} signedIn={false} account={null} />);

    expect(screen.getByRole("heading", { name: "Paper trade" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in to trade AAPL" })).toHaveAttribute(
      "href",
      "/login?callbackUrl=%2Fstocks%2FAAPL%3Ftf%3D1Y%26indicators%3Dsma_50",
    );
  });

  it("uses real buying power for percentage sizing", () => {
    render(<ContextualTradeTicket {...baseProps} signedIn account={account} />);

    fireEvent.click(screen.getByRole("button", { name: "Use 50% of buying power" }));
    expect(screen.getByLabelText("Quantity")).toHaveValue(2);
    expect(screen.getByText("$50.00")).toBeVisible();
  });

  it("omits buy shortcuts when account and symbol currencies differ", () => {
    render(
      <ContextualTradeTicket
        {...baseProps}
        currency="EUR"
        signedIn
        account={{ ...account, displayCurrency: "USD" }}
      />,
    );

    expect(screen.queryByRole("button", { name: /buying power/i })).not.toBeInTheDocument();
    expect(screen.getByText(/currency conversion is unavailable/i)).toBeVisible();
  });

  it("shows limit pricing and updates the estimated native notional", () => {
    render(<ContextualTradeTicket {...baseProps} signedIn account={account} />);

    fireEvent.click(screen.getByRole("button", { name: "Limit" }));
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "20" } });

    expect(screen.getByText("$60.00")).toBeVisible();
    expect(screen.getByText(/at your limit price/i)).toBeVisible();
  });

  it("reveals protective sell orders only when shares are available", () => {
    render(
      <ContextualTradeTicket
        {...baseProps}
        signedIn
        account={{
          ...account,
          position: {
            quantity: 8,
            availableQuantity: 5,
            averageCost: 20,
            marketValue: 200,
            unrealizedPnl: 40,
            returnPct: 25,
            allocationPct: 20,
          },
        }}
      />,
    );

    fireEvent.click(screen.getByText("Protect position"));
    expect(screen.getByRole("button", { name: "Stop loss" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Take profit" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Sell" }));
    fireEvent.click(screen.getByRole("button", { name: "Use maximum available shares" }));
    expect(screen.getByLabelText("Quantity")).toHaveValue(5);
  });
});
