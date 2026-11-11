import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { placeTradeAction } from "@/app/(product)/(authed)/trade/actions";
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

  it("reviews a market order before it can be placed", () => {
    render(
      <ContextualTradeTicket
        {...baseProps}
        closeDate="2025-04-04T00:00:00"
        signedIn
        account={account}
      />,
    );

    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));

    expect(screen.getByText("Review order")).toBeVisible();
    expect(screen.getByText("Market buy 3 AAPL")).toBeVisible();
    expect(screen.getByText("$25.00 · close of Apr 4, 2025")).toBeVisible();
    expect(screen.getByText("None in the simulator")).toBeVisible();
    expect(screen.getByText("$75.00", { selector: "dd" })).toBeVisible();
    expect(screen.getByText(/Fills now at the latest stored daily close/)).toBeVisible();
    expect(placeTradeAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Quantity")).toHaveValue(3);
  });

  it("warns in the review when a buy exceeds buying power", () => {
    render(<ContextualTradeTicket {...baseProps} signedIn account={account} />);

    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));

    expect(screen.getByText("-$150.00")).toHaveClass("text-warning");
    expect(screen.getByText(/more than your buying power/)).toBeVisible();
  });

  it("explains that a limit order fills at the close, not the limit", () => {
    render(<ContextualTradeTicket {...baseProps} signedIn account={account} />);

    fireEvent.click(screen.getByRole("button", { name: "Limit" }));
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Review order" }));

    expect(screen.getByText("Cash reserved until filled")).toBeVisible();
    expect(screen.getByText(/not at your limit itself/)).toBeVisible();
  });

  it("submits from the review and confirms the fill", async () => {
    vi.mocked(placeTradeAction).mockResolvedValueOnce({
      success: {
        ticker: "AAPL",
        side: "buy",
        quantity: "1",
        price: "25",
        currency: "USD",
        total_native: "25",
        total_usd: "25",
      },
    });
    render(<ContextualTradeTicket {...baseProps} signedIn account={account} />);

    fireEvent.click(screen.getByRole("button", { name: "Review order" }));
    fireEvent.click(screen.getByRole("button", { name: "Place buy order" }));

    expect(await screen.findByText("Your order was filled")).toBeVisible();
    expect(screen.getByText("Filled BUY 1 AAPL at $25.00")).toBeVisible();
    expect(placeTradeAction).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "New order" }));
    expect(screen.getByRole("button", { name: "Review order" })).toBeVisible();
  });
});
