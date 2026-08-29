import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AlertForm } from "@/components/alert-form";
import { OrderBlotterRow, PendingOrderQuote } from "@/components/order-blotter-row";
import type { PendingOrder } from "@/lib/api/trading";
import { currencyByTicker, formatNativePrice, tickerCurrency } from "@/lib/operational-trading";

vi.mock("@/app/(product)/(authed)/orders/actions", () => ({
  cancelOrderAction: vi.fn(),
}));

vi.mock("@/app/(product)/(authed)/alerts/actions", () => ({
  createAlertAction: vi.fn().mockResolvedValue({}),
}));

const currencies = currencyByTicker([
  { ticker: "7203.T", currency: "JPY" },
  { ticker: "SAP.DE", currency: "EUR" },
  { ticker: "AAPL", currency: "USD" },
]);

function toyotaLimit(overrides: Partial<PendingOrder> = {}): PendingOrder {
  return {
    id: 1,
    ticker: "7203.T",
    side: "sell",
    order_type: "limit",
    quantity: "100",
    limit_price: "2800",
    status: "pending",
    created_at: "2026-08-27T12:00:00Z",
    filled_at: null,
    fill_price: null,
    cancel_reason: null,
    ...overrides,
  };
}

describe("native operational currency lookup", () => {
  it("maps tickers to ISO codes and falls back to USD", () => {
    expect(tickerCurrency("7203.T", currencies)).toBe("JPY");
    expect(tickerCurrency("sap.de", currencies)).toBe("EUR");
    expect(tickerCurrency("UNKNOWN", currencies)).toBe("USD");
    expect(formatNativePrice("2800", "7203.T", currencies)).toBe("¥2,800");
    expect(formatNativePrice("91.50", "SAP.DE", currencies)).toBe("€91.50");
    expect(formatNativePrice("188.38", "AAPL", currencies)).toBe("$188.38");
    expect(formatNativePrice("2800", "7203.T", currencies)).not.toContain("$");
  });
});

describe("Orders blotter native prices", () => {
  it("formats the trigger price in the symbol currency", () => {
    render(
      <table>
        <tbody>
          <OrderBlotterRow order={toyotaLimit()} currencies={currencies} />
        </tbody>
      </table>,
    );
    expect(screen.getByText("¥2,800")).toBeVisible();
    expect(screen.queryByText("$2,800.00")).toBeNull();
  });

  it("formats the fill price in the symbol currency", () => {
    render(
      <table>
        <tbody>
          <OrderBlotterRow
            order={toyotaLimit({
              status: "filled",
              filled_at: "2026-08-27T20:45:00Z",
              fill_price: "2785",
            })}
            currencies={currencies}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("¥2,785")).toBeVisible();
    expect(screen.queryByText("$2,785.00")).toBeNull();
  });
});

describe("Trade pending-order context", () => {
  it("formats the queued quote in the symbol currency", () => {
    render(<PendingOrderQuote order={toyotaLimit()} currencies={currencies} />);
    expect(screen.getByText(/¥2,800/)).toBeVisible();
    expect(screen.queryByText(/\$2,800/)).toBeNull();
  });
});

describe("Watchlist and alert native prices", () => {
  it("formats a watchlist last close in JPY", () => {
    expect(formatNativePrice("2800.00", "7203.T", currencies)).toBe("¥2,800");
  });

  it("formats an alert target in EUR", () => {
    expect(formatNativePrice("91.50", "SAP.DE", currencies)).toBe("€91.50");
  });
});

describe("Alert form stored-close copy", () => {
  it("shows the current stored close in the symbol currency", () => {
    render(<AlertForm ticker="7203.T" lastClose="2800" currency="JPY" variant="inline" />);
    expect(screen.getByText(/Current stored close: ¥2,800/)).toBeVisible();
    expect(screen.queryByText(/\$2,800/)).toBeNull();
  });
});
