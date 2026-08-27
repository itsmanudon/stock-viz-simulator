import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PositionSummary } from "@/components/position-summary";
import { StockMetricsStrip } from "@/components/stock-metrics-strip";
import { StockResearchTabs } from "@/components/stock-research-tabs";
import { TickerOrders } from "@/components/ticker-orders";

vi.mock("@/app/(product)/(authed)/orders/actions", () => ({
  cancelOrderAction: vi.fn(),
}));

describe("stock workspace presentation", () => {
  it("renders a compact, labelled market metric strip", () => {
    render(
      <StockMetricsStrip
        currency="USD"
        metrics={{
          open: 110,
          high: 115,
          low: 109,
          previousClose: 108,
          volume: 1_250_000,
          rangeHigh: 150,
          rangeLow: 80,
          latestTimestamp: "2026-08-26",
        }}
        rsi={54.321}
      />,
    );

    expect(screen.getByText("Open")).toBeVisible();
    expect(screen.getByText("$110.00")).toBeVisible();
    expect(screen.getByText("1.25M")).toBeVisible();
    expect(screen.getByText("$80.00 – $150.00")).toBeVisible();
    expect(screen.getByText("54.32")).toBeVisible();
  });

  it("describes the user's relationship to a held security", () => {
    render(
      <PositionSummary
        ticker="AAPL"
        nativeCurrency="USD"
        displayCurrency="USD"
        position={{
          quantity: 0.000001,
          availableQuantity: 0.000001,
          averageCost: 20,
          marketValue: 200,
          unrealizedPnl: 40,
          returnPct: 25,
          allocationPct: 20,
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Your AAPL position" })).toBeVisible();
    expect(screen.getByText("0.000001")).toBeVisible();
    expect(screen.getByText("+$40.00")).toBeVisible();
    expect(screen.getByText("+25.00%")).toBeVisible();
    expect(screen.getByText("20.00%")).toBeVisible();
  });

  it("shows real pending order terms and cancellation", () => {
    render(
      <TickerOrders
        ticker="AAPL"
        currency="USD"
        orders={[
          {
            id: 4,
            ticker: "AAPL",
            side: "buy",
            order_type: "limit",
            quantity: "5",
            limit_price: "180",
            status: "pending",
            created_at: "2026-08-26T10:00:00Z",
            filled_at: null,
            fill_price: null,
            cancel_reason: null,
          },
        ]}
      />,
    );

    expect(screen.getByText("BUY LIMIT")).toBeVisible();
    expect(screen.getByText("5 AAPL @ $180.00")).toBeVisible();
    expect(screen.getByText("Pending")).toBeVisible();
    expect(screen.getByRole("button", { name: "Cancel AAPL buy limit order" })).toBeVisible();
  });

  it("distinguishes unavailable order data from a genuine empty state", () => {
    render(<TickerOrders ticker="AAPL" currency="USD" orders={null} />);

    expect(screen.getByText("Order data is temporarily unavailable.")).toBeVisible();
    expect(screen.queryByText("No pending orders for AAPL.")).not.toBeInTheDocument();
  });

  it("organizes secondary research in keyboard-capable tabs", async () => {
    const user = userEvent.setup();
    render(
      <StockResearchTabs
        overview={<p>Security overview content</p>}
        news={<p>News content</p>}
        positionOrders={<p>Position content</p>}
        discussion={<p>Discussion content</p>}
        newsCount={3}
        orderCount={1}
      />,
    );

    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "News 3" }));
    expect(screen.getByText("News content")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Position & orders 1" }));
    expect(screen.getByText("Position content")).toBeVisible();
  });
});
