import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import type {
  DividendSummary,
  PendingOrder,
  Portfolio,
  PortfolioAnalytics,
  PortfolioHistoryPoint,
} from "@/lib/api/trading";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

vi.mock("lightweight-charts", () => ({
  AreaSeries: "AreaSeries",
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  closeOptionAction: vi.fn(),
}));

vi.mock("@/app/(product)/(authed)/orders/actions", () => ({
  cancelOrderAction: vi.fn(),
}));

const portfolio: Portfolio = {
  portfolio_id: 1,
  display_currency: "USD",
  cash_balance: "23402",
  reserved_cash: "0",
  available_cash: "23402",
  market_value: "105018",
  total_value: "128420",
  total_cost_basis: "95000",
  unrealized_pl: "10018",
  options_market_value: "0",
  positions: [
    {
      ticker: "AAPL",
      name: "Apple Inc.",
      quantity: "25",
      currency: "USD",
      avg_cost: "221.40",
      last_close: "247.36",
      market_value_native: "6184",
      unrealized_pl_native: "649",
      market_value: "6184",
      unrealized_pl: "649",
      reserved_quantity: "0",
      available_quantity: "25",
    },
  ],
  option_positions: [],
};

const history: PortfolioHistoryPoint[] = [
  { date: "2026-06-01", nav: "120000" },
  { date: "2026-08-27", nav: "128420" },
];

const analytics: PortfolioAnalytics = {
  display_currency: "USD",
  history_days: 90,
  total_return_pct: 7.02,
  annualised_return_pct: 12.5,
  sharpe_ratio: 1.1,
  max_drawdown_pct: -4.2,
  risk_free_rate: 0.05,
  sector_allocation: [{ sector: "Technology", market_value: "105018", pct: 100 }],
  top_gainers: [
    {
      ticker: "AAPL",
      name: "Apple Inc.",
      sector: "Technology",
      unrealized_pl: "649",
      return_pct: 11.73,
    },
  ],
  top_losers: [],
};

const orders: PendingOrder[] = [
  {
    id: 4,
    ticker: "AAPL",
    side: "sell",
    order_type: "stop_loss",
    quantity: "3",
    limit_price: "220",
    status: "pending",
    created_at: "2026-08-26T10:00:00Z",
    filled_at: null,
    fill_price: null,
  },
];

const dividends: DividendSummary = { ytd_income: "55.25", projected: [], history: [] };

describe("portfolio workspace", () => {
  it("orders performance, operational holdings, and exposure into one workspace", () => {
    render(
      <PortfolioWorkspace
        portfolio={portfolio}
        history={history}
        analytics={analytics}
        orders={orders}
        dividends={dividends}
        range="3m"
        tab="positions"
      />,
    );

    const heading = screen.getByRole("heading", { level: 1, name: "Portfolio" });
    const tabs = screen.getByRole("tablist", { name: "Portfolio sections" });
    const allocation = screen.getByRole("heading", { name: "Equity sector allocation" });

    expect(screen.getByText("$128,420.00")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Positions" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Orders 1" })).toBeVisible();
    expect(screen.getByRole("table", { name: "Stock positions" })).toBeVisible();
    expect(heading.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      tabs.compareDocumentPosition(allocation) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Dividend income" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Options positions" })).not.toBeInTheDocument();
  });

  it("shows a focused starting state without chart or exposure noise for a new portfolio", () => {
    render(
      <PortfolioWorkspace
        portfolio={{
          ...portfolio,
          cash_balance: "100000",
          available_cash: "100000",
          market_value: "0",
          total_value: "100000",
          total_cost_basis: "0",
          unrealized_pl: "0",
          positions: [],
        }}
        history={[]}
        analytics={{ ...analytics, history_days: 0, sector_allocation: [], top_gainers: [] }}
        orders={[]}
        dividends={{ ytd_income: "0", projected: [], history: [] }}
        range="3m"
        tab="positions"
      />,
    );

    expect(screen.getByRole("heading", { name: "Your portfolio is ready" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Explore markets" })).toBeVisible();
    expect(screen.queryByRole("img", { name: /USD NAV chart/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Equity sector allocation" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Sharpe ratio")).not.toBeInTheDocument();
  });
});
