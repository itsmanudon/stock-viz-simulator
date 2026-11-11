import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { placeTradeAction } from "@/app/(product)/(authed)/trade/actions";
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
  { ticker: "7203.T", name: "Toyota Motor Corporation", currency: "JPY" },
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

  it("dates the stored close by its calendar day in every time zone (audit T2)", () => {
    // No zone on the timestamp: read as local time it became 2025-04-03 east
    // of UTC, while the stock page said Apr 4.
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="MSFT"
        quoteClose="400.00"
        quoteAt="2025-04-04T00:00:00"
        position={null}
        availableCash="100000"
        displayCurrency="USD"
      />,
    );
    expect(screen.getByText(/Last stored close .* · Apr 4, 2025/)).toBeVisible();
    expect(screen.queryByText(/2025-04-03/)).not.toBeInTheDocument();
  });

  it("keeps the fill announcement after the parent passes a new quote", () => {
    const { rerender } = render(
      <OrderTicket
        symbols={symbols}
        initialTicker="AAPL"
        quoteClose="188.38"
        quoteAt="2026-08-26T00:00:00Z"
        position={null}
        availableCash="100000"
        displayCurrency="USD"
      />,
    );

    expect(screen.getByLabelText("Symbol")).toHaveValue("AAPL");
    rerender(
      <OrderTicket
        symbols={symbols}
        initialTicker="AAPL"
        quoteClose="188.38"
        quoteAt="2026-08-26T00:00:00Z"
        position={{
          quantity: "1",
          availableQuantity: "1",
          reservedQuantity: "0",
          averageCost: "188.38",
          lastClose: "188.38",
          currency: "USD",
        }}
        availableCash="99811.62"
        displayCurrency="USD"
      />,
    );
    expect(screen.getByLabelText("Symbol")).toHaveValue("AAPL");
    expect(screen.getByRole("button", { name: /Review market buy/i })).toBeVisible();
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
    expect(screen.getByRole("button", { name: /Review stop-loss sell/i })).toBeVisible();
  });

  it("estimates notional in the symbol-native currency", () => {
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="7203.T"
        quoteClose="2800"
        quoteAt="2026-08-26T00:00:00Z"
        position={null}
        availableCash="100000"
        displayCurrency="USD"
      />,
    );

    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "2" } });
    expect(screen.getByText("¥5,600")).toBeVisible();
    expect(screen.getByText(/Available cash \$100,000\.00/)).toBeVisible();
  });

  it("reviews the order before placing it, then confirms the fill", async () => {
    vi.mocked(placeTradeAction).mockResolvedValueOnce({
      success: {
        ticker: "AAPL",
        side: "buy",
        quantity: "2",
        price: "188.38",
        currency: "USD",
        total_native: "376.76",
        total_usd: "376.76",
      },
    });
    render(
      <OrderTicket
        symbols={symbols}
        initialTicker="AAPL"
        quoteClose="188.38"
        quoteAt="2025-04-04T00:00:00"
        position={null}
        availableCash="1000"
        displayCurrency="USD"
      />,
    );

    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /Review market buy/i }));

    expect(screen.getByText("Market buy 2 AAPL")).toBeVisible();
    expect(screen.getByText("$188.38 · close of Apr 4, 2025")).toBeVisible();
    expect(placeTradeAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Place market buy/i }));
    expect(await screen.findByText("Your order was filled")).toBeVisible();
    expect(screen.getByText("Filled BUY 2 AAPL @ $188.38")).toBeVisible();
  });
});
