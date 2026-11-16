import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertsWidget } from "@/components/dashboard/alerts-widget";
import { AllocationWidget } from "@/components/dashboard/allocation-widget";
import { DeltaPill } from "@/components/dashboard/delta-pill";
import { MoversWidget } from "@/components/dashboard/movers-widget";
import { OrdersWidget } from "@/components/dashboard/orders-widget";
import { PortfolioHero } from "@/components/dashboard/portfolio-hero";
import { WatchlistWidget } from "@/components/dashboard/watchlist-widget";
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
  unrealized_pl_equity: "2000",
  unrealized_pl_options: "0",
  realized_pl: "0",
  realized_pl_unavailable: 0,
  options_market_value: "0",
  positions: [],
  option_positions: [],
  valuation_warnings: [],
  cash_by_currency: [],
  base_currency: "USD",
  base_currency_locked: true,
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

    // The headline figure dims its cents in a nested span, so match the whole
    // paragraph's text rather than a single text node.
    expect(
      screen.getByText(
        (_, element) => element?.tagName === "P" && element.textContent === "$20,000.00",
      ),
    ).toBeVisible();
    expect(screen.getByText("+11.11%")).toBeVisible();
    expect(screen.getByText("+$2,000.00")).toBeVisible();
  });

  it("explains the missing delta rather than rendering an empty chart", () => {
    render(<PortfolioHero portfolio={portfolio} history={[]} />);

    expect(screen.getByText(/two days of history/i)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("adds the last session's move once there are three snapshots", () => {
    render(
      <PortfolioHero
        portfolio={portfolio}
        history={[
          { date: "2026-08-01", nav: "18000" },
          { date: "2026-08-27", nav: "19000" },
          { date: "2026-08-28", nav: "20000" },
        ]}
      />,
    );
    expect(screen.getByText("last session")).toBeVisible();
    expect(screen.getByText("+$1,000.00")).toBeVisible();
  });

  it("labels the value as simulated and dates it by the latest snapshot", () => {
    render(
      <PortfolioHero
        portfolio={portfolio}
        history={[
          { date: "2026-08-01", nav: "18000" },
          { date: "2026-08-28", nav: "20000" },
        ]}
      />,
    );

    expect(screen.getByText("Simulated")).toBeVisible();
    expect(screen.getByText(/snapshot of Aug 28, 2026/)).toBeVisible();
    // The cents are dimmed in their own span but the figure reads as one value.
    expect(screen.getByText(".00")).toHaveClass("figure-minor");
  });

  it("offers the four account actions as links", () => {
    render(<PortfolioHero portfolio={portfolio} history={[]} />);

    const actions = within(screen.getByRole("navigation", { name: "Portfolio actions" }));
    expect(actions.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/trade",
      "/orders",
      "/backtest",
      "/alerts",
    ]);
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

    render(<OrdersWidget orders={orders} />);
    const list = screen.getByRole("list");

    expect(within(list).getByText("MSFT")).toBeVisible();
    expect(within(list).getByText("buy")).toBeVisible();
    expect(within(list).getByText(/Limit · 10 sh/)).toBeVisible();
    expect(within(list).getByText("$410.50")).toBeVisible();
  });

  it("prices an order in its symbol's currency, not the display currency", () => {
    const order: PendingOrder = {
      id: 8,
      ticker: "TCS.NS",
      side: "buy",
      order_type: "limit",
      quantity: "50",
      limit_price: "2980.00",
      status: "pending",
      created_at: "2026-08-27T10:00:00Z",
      filled_at: null,
      fill_price: null,
      cancel_reason: null,
    };
    render(<OrdersWidget orders={[order]} currencies={{ "TCS.NS": "INR" }} />);
    expect(screen.getByText("₹2,980.00")).toBeVisible();
    expect(screen.getByText(/Checked after each weekday close/)).toBeVisible();
  });

  it("distinguishes an unavailable fetch from a genuinely empty blotter", () => {
    const { rerender } = render(<OrdersWidget orders={null} />);
    expect(screen.getByText(/unavailable/i)).toBeVisible();

    rerender(<OrdersWidget orders={[]} />);
    expect(screen.getByText(/No working orders/i)).toBeVisible();
  });
});

describe("AlertsWidget", () => {
  it("puts fired alerts first, then lists armed ones linked to their symbol (audit F3)", () => {
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
    const armed = screen.getByRole("list", { name: "Armed alerts" });
    expect(within(armed).getByRole("link", { name: /TSLA.*Below.*200\.00/ })).toHaveAttribute(
      "href",
      "/stocks/TSLA",
    );
  });

  it("shows four alerts at most and links the rest", () => {
    const alerts: Alert[] = ["A", "B", "C", "D", "E", "F"].map((ticker, index) => ({
      id: index + 10,
      ticker,
      direction: "above",
      target_price: "10",
      created_at: "2026-08-21T10:00:00Z",
      triggered_at: null,
      dismissed_at: null,
    }));
    render(<AlertsWidget alerts={alerts} />);
    expect(
      within(screen.getByRole("list", { name: "Armed alerts" })).getAllByRole("listitem"),
    ).toHaveLength(4);
    expect(screen.getByRole("link", { name: "2 more" })).toHaveAttribute("href", "/alerts");
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
  function analyticsWith(
    sector_allocation: PortfolioAnalytics["sector_allocation"],
  ): PortfolioAnalytics {
    return {
      display_currency: "USD",
      history_days: 30,
      total_return_pct: null,
      annualised_return_pct: null,
      sharpe_ratio: null,
      max_drawdown_pct: null,
      risk_free_rate: 0,
      sector_allocation,
      top_gainers: [],
      top_losers: [],
    };
  }

  it("explains a book with no sector data instead of drawing Unknown 100% (audit D3)", () => {
    render(
      <AllocationWidget
        analytics={analyticsWith([{ sector: "Unknown", market_value: "5000", pct: 100 }])}
      />,
    );
    expect(screen.getByText(/Sector data has not been recorded/)).toBeVisible();
    expect(screen.queryByText("Unknown")).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("names a partly unclassified bucket plainly", () => {
    render(
      <AllocationWidget
        analytics={analyticsWith([
          { sector: "Technology", market_value: "4000", pct: 80 },
          { sector: "Unknown", market_value: "1000", pct: 20 },
        ])}
      />,
    );
    expect(screen.getByText("Sector not recorded")).toBeVisible();
  });
});

describe("WatchlistWidget", () => {
  it("shows each price in its row's currency, not the raw stored string (audit T7)", () => {
    render(
      <WatchlistWidget
        watchlist={[
          {
            ticker: "AAPL",
            name: "Apple Inc.",
            sector: null,
            added_at: "2026-08-01T00:00:00Z",
            last_close: "312.320000",
            last_close_at: "2025-04-04T00:00:00",
            currency: "USD",
          },
          {
            ticker: "RELIANCE.NS",
            name: "Reliance Industries",
            sector: null,
            added_at: "2026-08-01T00:00:00Z",
            last_close: "1250.5",
            last_close_at: "2025-04-07T00:00:00",
            currency: "INR",
          },
        ]}
      />,
    );
    expect(screen.getByText("$312.32")).toBeVisible();
    expect(screen.getByText("₹1,250.50")).toBeVisible();
    expect(screen.queryByText("312.320000")).not.toBeInTheDocument();
  });

  it("dates each price by its own close (audit RS-13)", () => {
    render(
      <WatchlistWidget
        watchlist={[
          {
            ticker: "AAPL",
            name: "Apple Inc.",
            sector: null,
            added_at: "2026-08-01T00:00:00Z",
            last_close: "188.38",
            last_close_at: "2025-04-04T00:00:00",
            currency: "USD",
          },
          {
            ticker: "NEW",
            name: "No bars yet",
            sector: null,
            added_at: "2026-08-01T00:00:00Z",
            last_close: null,
            last_close_at: null,
            currency: "USD",
          },
        ]}
      />,
    );
    expect(screen.getByText("Apr 4, 2025")).toBeVisible();
    expect(screen.getAllByText(/\d{4}$/)).toHaveLength(1);
  });
});

describe("AlertsWidget currency", () => {
  it("formats each target in the currency its row carries", () => {
    render(
      <AlertsWidget
        alerts={[
          {
            id: 1,
            ticker: "RELIANCE.NS",
            direction: "above",
            target_price: "1500",
            created_at: "2026-08-01T00:00:00",
            triggered_at: null,
            dismissed_at: null,
            currency: "INR",
          },
        ]}
      />,
    );
    expect(screen.getByText(/₹1,500\.00/)).toBeVisible();
  });
});
