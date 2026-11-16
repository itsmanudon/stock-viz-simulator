import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioIncome } from "@/components/portfolio-income";
import { PortfolioOptions } from "@/components/portfolio-options";
import { PortfolioOrders } from "@/components/portfolio-orders";
import type { DividendSummary, PendingOrder, PortfolioOption, Position } from "@/lib/api/trading";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  closeOptionAction: vi.fn(),
  closeOptionFormAction: vi.fn(),
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
  side: "long",
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
  cancel_reason: null,
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
      currency: "USD",
      base_value: "55.25",
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
    // The values are modelled, and the subtitle says from what (Phase 9.6).
    expect(screen.getByText(/stored option chain.*implied volatility/)).toBeVisible();
    // No Greeks in the payload: a dash, never an invented zero.
    expect(within(table).getByLabelText("Greeks unavailable")).toBeVisible();
  });

  it("shows each contract's per-share delta and theta (Phase 9.1, UX-5)", () => {
    const priced = {
      ...option,
      greeks: { delta: 0.5321, gamma: 0.0012, theta: -4.2, vega: 310, rho: 120 },
    };
    render(<PortfolioOptions positions={[priced]} displayCurrency="EUR" />);

    const table = screen.getByRole("table", { name: "Options positions" });
    expect(within(table).getByLabelText("Delta 0.53, theta -4.20 a day")).toHaveTextContent(
      "Δ 0.53 · Θ -¥4",
    );
    expect(screen.getByText(/Greeks are per share; theta is per day/)).toBeVisible();
  });

  it("shows a written covered call as a liability you buy back (Phase 9.2)", () => {
    const written = {
      ...option,
      ticker: "AAPL",
      currency: "USD",
      side: "short" as const,
      premium_paid: "746.40",
      market_value: "-512.30",
      market_value_native: "-512.30",
      unrealized_pl: "234.10",
    };
    render(<PortfolioOptions positions={[written]} displayCurrency="USD" />);

    const table = screen.getByRole("table", { name: "Options positions" });
    expect(within(table).getByText("Covered call (written)")).toBeVisible();
    expect(within(table).getByText("received")).toBeVisible();
    const buyBack = within(table).getByRole("button", {
      name: "Close AAPL written call position",
    });
    expect(buyBack).toHaveTextContent("Buy back");
    fireEvent.click(buyBack);
    expect(within(table).getByText("Buy back for about $512.30?")).toBeVisible();
  });

  it("labels a leg of a spread with its strategy (Phase 9.3)", () => {
    const leg = {
      ...option,
      ticker: "AAPL",
      currency: "USD",
      side: "short" as const,
      strategy: "Bear call spread",
    };
    render(<PortfolioOptions positions={[leg]} displayCurrency="USD" />);

    const table = screen.getByRole("table", { name: "Options positions" });
    expect(within(table).getByText("call (written)")).toBeVisible();
    expect(within(table).getByText("Leg of a bear call spread")).toBeVisible();
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
    expect(screen.getByText("Credited in each dividend's own currency")).toBeVisible();
  });

  it("shows a non-USD credit in its own currency (Phase 4.5c)", () => {
    const eur: DividendSummary = {
      ...dividends,
      history: [
        {
          ticker: "SAP.DE",
          ex_date: "2026-05-04",
          amount_credited: "22.00",
          currency: "EUR",
          base_value: "23.76",
          credited_at: "2026-05-04T12:00:00Z",
        },
      ],
    };
    render(<PortfolioIncome dividends={eur} positions={positions} />);

    expect(screen.getByText("+€22.00")).toBeVisible();
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
