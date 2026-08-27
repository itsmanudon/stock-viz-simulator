import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioIncome } from "@/components/portfolio-income";
import { PortfolioOptions } from "@/components/portfolio-options";
import { PortfolioOrders } from "@/components/portfolio-orders";
import type { DividendSummary, PendingOrder, PortfolioOption, Position } from "@/lib/api/trading";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  closeOptionAction: vi.fn(),
}));

vi.mock("@/app/(product)/(authed)/orders/actions", () => ({
  cancelOrderAction: vi.fn(),
}));

const option: PortfolioOption = {
  option_id: 8,
  ticker: "7203.T",
  option_type: "call",
  strike: "3000",
  expiry: "2026-12-18",
  quantity: 2,
  currency: "JPY",
  premium_paid: "420.00",
  market_value_native: "81000",
  market_value: "505.25",
  unrealized_pl: "85.25",
};

const order: PendingOrder = {
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
};

const positions: Position[] = [
  {
    ticker: "7203.T",
    name: "Toyota Motor Corporation",
    quantity: "1000",
    currency: "JPY",
    avg_cost: "2500",
    last_close: "2800",
    market_value_native: "2800000",
    unrealized_pl_native: "300000",
    market_value: "18900",
    unrealized_pl: "2100",
    reserved_quantity: "0",
    available_quantity: "1000",
  },
];

const dividends: DividendSummary = {
  ytd_income: "825.40",
  projected: [
    { ticker: "7203.T", projected_ex_date: "2026-09-29", projected_amount: "7500" },
    { ticker: "UNKNOWN", projected_ex_date: null, projected_amount: "25" },
  ],
  history: [
    {
      ticker: "AAPL",
      ex_date: "2026-08-10",
      amount_credited: "55.25",
      credited_at: "2026-08-10T12:00:00Z",
    },
  ],
};

describe("portfolio operational panels", () => {
  it("presents portfolio-payload options with their real currency bases", () => {
    render(<PortfolioOptions positions={[option]} displayCurrency="EUR" />);

    const table = screen.getByRole("table", { name: "Options positions" });
    expect(within(table).getByRole("link", { name: "7203.T" })).toHaveAttribute(
      "href",
      "/stocks/7203.T",
    );
    expect(within(table).getByText("call", { exact: true })).toBeVisible();
    expect(within(table).getByText("¥3,000")).toBeVisible();
    expect(within(table).getByText("$420.00")).toBeVisible();
    expect(within(table).getByText("€505.25")).toBeVisible();
    expect(within(table).getByText("¥81,000 native")).toBeVisible();
    expect(within(table).getByText("Gain +€85.25")).toBeVisible();
    expect(within(table).getByRole("button", { name: "Close 7203.T call position" })).toBeVisible();
    expect(screen.queryByText(/implied volatility/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/delta|gamma|theta|vega/i)).not.toBeInTheDocument();
  });

  it("uses a concise true empty state for options", () => {
    render(<PortfolioOptions positions={[]} displayCurrency="USD" />);
    expect(screen.getByText("No option positions are currently open.")).toBeVisible();
  });

  it("shows pending orders without inventing a trigger currency", () => {
    render(<PortfolioOrders orders={[order]} />);

    const table = screen.getByRole("table", { name: "Pending portfolio orders" });
    expect(within(table).getByText("Native quote")).toBeVisible();
    expect(within(table).getByText("180.00")).toBeVisible();
    expect(within(table).queryByText("$180.00")).not.toBeInTheDocument();
    expect(within(table).getByText("BUY")).toBeVisible();
    expect(within(table).getByText("Limit")).toBeVisible();
    expect(
      within(table).getByRole("button", { name: "Cancel AAPL buy limit order" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "View all orders" })).toHaveAttribute(
      "href",
      "/orders",
    );
  });

  it("distinguishes unavailable orders from a successful empty response", () => {
    const { rerender } = render(<PortfolioOrders orders={null} />);
    expect(screen.getByText("Order data is temporarily unavailable.")).toBeVisible();

    rerender(<PortfolioOrders orders={[]} />);
    expect(screen.getByText(/No pending orders across your portfolio\./)).toBeVisible();
    expect(screen.queryByText("Order data is temporarily unavailable.")).not.toBeInTheDocument();
  });

  it("labels credited USD income separately from native-currency projections", () => {
    render(<PortfolioIncome dividends={dividends} positions={positions} />);

    expect(screen.getByText("YTD credited income · USD")).toBeVisible();
    expect(screen.getByText("$825.40")).toBeVisible();
    expect(screen.getByText("¥7,500")).toBeVisible();
    expect(screen.getByText("Native projection")).toBeVisible();
    expect(screen.getByText("25.00 · Currency unavailable")).toBeVisible();
    expect(screen.getByText("+$55.25")).toBeVisible();
    expect(screen.getByText("Credited in USD")).toBeVisible();
  });

  it("distinguishes unavailable dividend data from a successful no-income state", () => {
    const { rerender } = render(<PortfolioIncome dividends={null} positions={positions} />);
    expect(screen.getByText("Income data is temporarily unavailable.")).toBeVisible();

    rerender(
      <PortfolioIncome
        dividends={{ ytd_income: "0", projected: [], history: [] }}
        positions={positions}
      />,
    );
    expect(screen.getByText("No dividend income has been credited yet.")).toBeVisible();
    expect(screen.queryByText("Income data is temporarily unavailable.")).not.toBeInTheDocument();
  });
});
