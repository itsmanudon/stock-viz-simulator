import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertsWidget } from "@/components/dashboard/alerts-widget";
import { AllocationWidget } from "@/components/dashboard/allocation-widget";
import { DeltaPill } from "@/components/dashboard/delta-pill";
import { MoversWidget } from "@/components/dashboard/movers-widget";
import { OrdersWidget } from "@/components/dashboard/orders-widget";
import { PortfolioHero } from "@/components/dashboard/portfolio-hero";
import type { Alert } from "@/lib/api/alerts";
import type { PendingOrder, Portfolio, PortfolioAnalytics } from "@/lib/api/trading";

const portfolio: Portfolio = {
  portfolio_id: 1,
  display_currency: "USD",
  cash_balance: "5000",
  reserved_cash: "0",
  available_cash: "5000",
  market_value: "15000",
  total_value: "20000",
  total_cost_basis: "18000",
  unrealized_pl: "2000",
  options_market_value: "0",
  positions: [],
  option_positions: [],
};

describe("DeltaPill", () => {
  it("derives tone from the sign of the value", () => {
    const { rerender } = render(<DeltaPill value="+9.30%" />);
    expect(screen.getByText("+9.30%")).toHaveClass("bg-positive-soft");

    rerender(<DeltaPill value="-4.10%" />);
    expect(screen.getByText("-4.10%")).toHaveClass("bg-negative-soft");
  });

  it("honours an explicit tone override", () => {
    render(<DeltaPill value="+1.00%" tone="neutral" />);
    expect(screen.getByText("+1.00%")).toHaveClass("bg-neutral-soft");
  });
});

describe("PortfolioHero", () => {
  it("shows total value and the change across the charted window", () => {
    render(
      <PortfolioHero
        portfolio={portfolio}
        history={[
          { date: "2026-08-01", nav: "18000" },
          { date: "2026-08-28", nav: "20000" },
        ]}
      />,
    );

    expect(screen.getByText("$20,000.00")).toBeVisible();
    expect(screen.getByText("+11.11%")).toBeVisible();
    expect(screen.getByText("+$2,000.00")).toBeVisible();
  });

  it("explains the missing delta rather than rendering an empty chart", () => {
    render(<PortfolioHero portfolio={portfolio} history={[]} />);

    expect(screen.getByText(/two days of history/i)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("MoversWidget", () => {
  it("lists gainers and losers with links to each symbol", () => {
    const analytics = {
      display_currency: "USD",
      history_days: 30,
      total_return_pct: 11.1,
      annualised_return_pct: null,
      sharpe_ratio: null,
      max_drawdown_pct: null,
      risk_free_rate: 0,
      sector_allocation: [],
      top_gainers: [
        {
          ticker: "AAPL",
          name: "Apple Inc.",
          sector: "Tech",
          unrealized_pl: "800",
          return_pct: 12.5,
        },
      ],
      top_losers: [
        {
          ticker: "XOM",
          name: "Exxon Mobil",
          sector: "Energy",
          unrealized_pl: "-140",
          return_pct: -3.2,
        },
      ],
    } satisfies PortfolioAnalytics;

    render(<MoversWidget analytics={analytics} />);

    expect(screen.getByRole("link", { name: /AAPL/ })).toHaveAttribute("href", "/stocks/AAPL");
    expect(screen.getByText("+12.50%")).toBeVisible();
    expect(screen.getByText("-3.20%")).toBeVisible();
  });

  it("falls back to an empty state when analytics are unavailable", () => {
    render(<MoversWidget analytics={null} />);
    expect(screen.getByText(/Open a position/i)).toBeVisible();
  });
});

describe("OrdersWidget", () => {
  it("renders each working order with its side, type and limit", () => {
    const orders: PendingOrder[] = [
      {
        id: 7,
        ticker: "MSFT",
        side: "buy",
        order_type: "limit",
        quantity: "10",
        limit_price: "410.50",
        status: "pending",
        created_at: "2026-08-27T10:00:00Z",
        filled_at: null,
        fill_price: null,
        cancel_reason: null,
      },
    ];

    render(<OrdersWidget orders={orders} displayCurrency="USD" />);
    const list = screen.getByRole("list");

    expect(within(list).getByText("MSFT")).toBeVisible();
    expect(within(list).getByText("buy")).toBeVisible();
    expect(within(list).getByText(/Limit · 10 sh/)).toBeVisible();
    expect(within(list).getByText("$410.50")).toBeVisible();
  });

  it("distinguishes an unavailable fetch from a genuinely empty blotter", () => {
    const { rerender } = render(<OrdersWidget orders={null} displayCurrency="USD" />);
    expect(screen.getByText(/unavailable/i)).toBeVisible();

    rerender(<OrdersWidget orders={[]} displayCurrency="USD" />);
    expect(screen.getByText(/No working orders/i)).toBeVisible();
  });
});

describe("AlertsWidget", () => {
  it("surfaces triggered alerts and summarises the armed ones", () => {
    const alerts: Alert[] = [
      {
        id: 1,
        ticker: "NVDA",
        direction: "above",
        target_price: "900.00",
        created_at: "2026-08-20T10:00:00Z",
        triggered_at: "2026-08-27T14:00:00Z",
        dismissed_at: null,
      },
      {
        id: 2,
        ticker: "TSLA",
        direction: "below",
        target_price: "200.00",
        created_at: "2026-08-21T10:00:00Z",
        triggered_at: null,
        dismissed_at: null,
      },
    ];

    render(<AlertsWidget alerts={alerts} />);

    expect(screen.getByRole("link", { name: /NVDA crossed above/ })).toBeVisible();
    expect(screen.getByText("1 alert armed and waiting.")).toBeVisible();
  });

  it("ignores alerts the user already dismissed", () => {
    render(
      <AlertsWidget
        alerts={[
          {
            id: 3,
            ticker: "AMD",
            direction: "above",
            target_price: "150.00",
            created_at: "2026-08-01T10:00:00Z",
            triggered_at: "2026-08-02T10:00:00Z",
            dismissed_at: "2026-08-02T11:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.queryByText(/AMD/)).not.toBeInTheDocument();
    expect(screen.getByText(/No alerts set/i)).toBeVisible();
  });
});

describe("AllocationWidget", () => {
  it("scales each bar against the largest sector weight", () => {
    render(
      <AllocationWidget
        analytics={
          {
            display_currency: "USD",
            history_days: 30,
            total_return_pct: null,
            annualised_return_pct: null,
            sharpe_ratio: null,
            max_drawdown_pct: null,
            risk_free_rate: 0,
            sector_allocation: [
              { sector: "Technology", market_value: "12000", pct: 60 },
              { sector: "Energy", market_value: "3000", pct: 15 },
            ],
            top_gainers: [],
            top_losers: [],
          } satisfies PortfolioAnalytics
        }
      />,
    );

    expect(screen.getByText("60.0%")).toBeVisible();
    // Largest sector fills the track; the rest are relative to it.
    expect(screen.getByRole("img", { name: /Technology: 60.0 percent/ }).firstChild).toHaveStyle({
      width: "100%",
    });
    expect(screen.getByRole("img", { name: /Energy: 15.0 percent/ }).firstChild).toHaveStyle({
      width: "25%",
    });
  });
});
