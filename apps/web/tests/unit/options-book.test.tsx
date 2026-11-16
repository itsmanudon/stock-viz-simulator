import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExpirationView, OptionsGreeks } from "@/components/options-book";
import type { OptionsBook } from "@/lib/api/options";

vi.mock("@/app/(product)/(authed)/trade/options-actions", () => ({
  closeStrategyFormAction: vi.fn(),
}));

const { PortfolioStrategies } = await import("@/components/portfolio-strategies");

const BOOK: OptionsBook = {
  underlyings: [
    {
      ticker: "AAPL",
      spot: "104",
      delta_shares: 31.5,
      dollar_delta: 3276,
      gamma_shares: 1.2,
      theta_per_day: -4.1,
      vega_per_point: 12.3,
      rho_per_point: 2.1,
    },
  ],
  dollar_delta: 3276,
  theta_per_day: -4.1,
  vega_per_point: 12.3,
  rho_per_point: 2.1,
  expirations: [
    {
      expiry: "2026-09-23",
      items: [
        {
          label: "Bull call spread",
          legs: ["Long 1 AAPL 100.00 call", "Short 1 AAPL 110.00 call"],
          at_risk: "400.00",
          outcome: "Settles in cash: net +400.00",
          net_cash: "400.00",
          strategy_id: 7,
        },
        {
          label: "Short 1 AAPL 110.00 call",
          legs: ["Short 1 AAPL 110.00 call"],
          at_risk: null,
          outcome: "Expires; the premium is kept and the shares released",
          net_cash: "0",
          strategy_id: 8,
        },
      ],
    },
  ],
  unpriced: [],
  method: "Black-Scholes Greeks at the latest close",
};

describe("options book", () => {
  it("states the book's Greeks in money", () => {
    render(<OptionsGreeks book={BOOK} />);
    const section = screen.getByRole("region", { name: "Options Greeks" });
    expect(section).toHaveTextContent("+$3,276.00");
    expect(section).toHaveTextContent("−$4.10/day");
    expect(within(section).getByRole("table", { name: "Greeks by underlying" })).toHaveTextContent(
      "31.5",
    );
  });

  it("groups legs by expiry with what today's close would do", () => {
    render(<ExpirationView book={BOOK} />);
    const section = screen.getByRole("region", { name: "Expirations" });
    expect(section).toHaveTextContent("2026-09-23");
    expect(section).toHaveTextContent("Settles in cash: net +400.00");
    expect(section).toHaveTextContent("At risk $400.00");
    expect(section).toHaveTextContent("Shares at risk");
  });

  it("renders nothing without options", () => {
    const empty = { ...BOOK, underlyings: [], expirations: [] };
    const { container } = render(
      <>
        <OptionsGreeks book={empty} />
        <ExpirationView book={empty} />
      </>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("closes a strategy in two steps", () => {
    render(
      <PortfolioStrategies
        strategies={[
          {
            id: 7,
            kind: "bull_call",
            label: "Bull call spread",
            status: "open",
            net_premium: "-400.00",
            collateral: "0",
            max_loss: "400.00",
            max_gain: "600.00",
            opened_at: "2026-11-16T10:00:00",
            legs: [
              {
                id: 1,
                ticker: "AAPL",
                option_type: "call",
                strike: "100",
                expiry: "2026-09-23",
                quantity: 1,
                premium_paid: "600",
                status: "open",
                opened_at: "",
                current_value: "0",
                greeks: { delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0 },
                side: "long",
              },
            ],
          },
        ]}
      />,
    );
    const item = screen.getByRole("listitem", { name: "Bull call spread on AAPL" });
    expect(item).toHaveTextContent("Paid $400.00 · can lose at most $400.00");
    fireEvent.click(within(item).getByRole("button", { name: "Close Bull call spread on AAPL" }));
    expect(within(item).getByText(/Close every leg at its model value/)).toBeVisible();
  });
});
