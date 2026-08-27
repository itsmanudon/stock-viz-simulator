import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrderTicket } from "@/components/order-ticket";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/trade",
}));

vi.mock("@/app/(product)/(authed)/trade/actions", () => ({
  placeTradeAction: vi.fn().mockResolvedValue({}),
  placeOrderAction: vi.fn().mockResolvedValue({}),
}));

const symbols = [
  { ticker: "AAPL", name: "Apple Inc.", currency: "USD" },
  { ticker: "MSFT", name: "Microsoft", currency: "USD" },
];

describe("OrderTicket", () => {
  it("prefills ticker and writes it back to the URL", () => {
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="MSFT"
        quoteClose="400.00"
        quoteAt="2026-08-26T00:00:00Z"
        position={null}
        availableCash="100000"
        displayCurrency="USD"
      />,
    );

    const select = screen.getByLabelText("Symbol");
    expect(select).toHaveValue("MSFT");
    fireEvent.change(select, { target: { value: "AAPL" } });
    expect(replace).toHaveBeenCalledWith("/trade?ticker=AAPL", { scroll: false });
  });

  it("shows buying-power context for buys and estimated notional from the stored close", () => {
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="AAPL"
        quoteClose="25.00"
        quoteAt="2026-08-26T00:00:00Z"
        position={null}
        availableCash="100.00"
        displayCurrency="USD"
      />,
    );

    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "2" } });
    expect(screen.getByText("$50.00")).toBeVisible();
    expect(screen.getByText(/Available cash \$100\.00/)).toBeVisible();
    expect(screen.getByText(/latest stored daily close/i)).toBeVisible();
  });

  it("locks stop-loss to sell and asks for a trigger", () => {
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="AAPL"
        quoteClose="25.00"
        quoteAt={null}
        position={{
          quantity: "8",
          availableQuantity: "5",
          reservedQuantity: "3",
          averageCost: "20",
          lastClose: "25",
          currency: "USD",
        }}
        availableCash="100000"
        displayCurrency="USD"
      />,
    );

    fireEvent.change(screen.getByLabelText("Order type"), { target: { value: "stop_loss" } });
    expect(screen.getByText(/orders are sell-only in this simulator/i)).toBeVisible();
    expect(screen.getByLabelText("Trigger price")).toBeVisible();
    expect(screen.getByText(/5 shares available after pending sells/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Submit stop-loss sell/i })).toBeVisible();
  });
});
