import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OrderCard } from "@/components/order-blotter-row";
import type { PendingOrder } from "@/lib/api/trading";

vi.mock("@/app/(product)/(authed)/orders/actions", () => ({
  cancelOrderAction: vi.fn(),
}));

function order(overrides: Partial<PendingOrder> = {}): PendingOrder {
  return {
    id: 7,
    ticker: "AAPL",
    side: "buy",
    order_type: "limit",
    quantity: "3",
    limit_price: "180",
    status: "pending",
    created_at: "2026-11-10T14:05:00Z",
    filled_at: null,
    fill_price: null,
    cancel_reason: null,
    ...overrides,
  } as PendingOrder;
}

describe("OrderCard", () => {
  it("carries the row's figures and a cancel action for a pending order", () => {
    render(
      <ul>
        <OrderCard order={order()} currencies={{ AAPL: "USD" }} />
      </ul>,
    );

    expect(screen.getByRole("link", { name: "AAPL" })).toHaveAttribute("href", "/stocks/AAPL");
    expect(screen.getByText("$180.00")).toBeVisible();
    // Times are stored in UTC and say so (audit T4).
    expect(screen.getByText(/Nov 10, 2026.*UTC/)).toBeVisible();
    expect(screen.getByText(/Waiting on the next stored daily close/)).toBeVisible();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeVisible();
  });

  it("offers Trade instead of Cancel once the order has filled", () => {
    render(
      <ul>
        <OrderCard
          order={order({
            status: "filled",
            filled_at: "2026-11-11T21:45:00Z",
            fill_price: "179.5",
          })}
          currencies={{ AAPL: "USD" }}
        />
      </ul>,
    );

    expect(screen.getByText("$179.50")).toBeVisible();
    expect(screen.getByRole("link", { name: "Trade" })).toHaveAttribute(
      "href",
      "/trade?ticker=AAPL",
    );
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
  });
});
