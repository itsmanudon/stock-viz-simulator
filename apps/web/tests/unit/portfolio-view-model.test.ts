import { describe, expect, it } from "vitest";

import type { Position } from "@/lib/api/trading";
import {
  buildPortfolioHref,
  calculateNavChange,
  calculatePortfolioWeight,
  currencyForProjectedDividend,
  formatCurrency,
  formatQuantity,
  formatSignedPercent,
  parsePortfolioRange,
  parsePortfolioTab,
  portfolioRangeDays,
} from "@/lib/portfolio-view-model";

const positions: Position[] = [
  {
    ticker: "7203.T",
    name: "Toyota Motor Corporation",
    quantity: "10",
    currency: "JPY",
    avg_cost: "2500",
    last_close: "2800",
    market_value_native: "28000",
    unrealized_pl_native: "3000",
    market_value: "189",
    unrealized_pl: "20.25",
    reserved_quantity: "0",
    available_quantity: "10",
  },
];

describe("portfolio view model", () => {
  it("normalizes ranges and tabs while preserving valid URL state", () => {
    expect(parsePortfolioRange(undefined)).toBe("3m");
    expect(parsePortfolioRange("1y")).toBe("1y");
    expect(parsePortfolioRange("bad")).toBe("3m");
    expect(portfolioRangeDays("1m")).toBe(30);
    expect(portfolioRangeDays("all")).toBeNull();
    expect(parsePortfolioTab("orders")).toBe("orders");
    expect(parsePortfolioTab("bad")).toBe("positions");
    expect(buildPortfolioHref({ range: "1y", tab: "orders" })).toBe(
      "/portfolio?range=1y&tab=orders",
    );
    expect(buildPortfolioHref({ range: "3m", tab: "positions" })).toBe(
      "/portfolio?range=3m",
    );
  });

  it("calculates selected-range USD NAV change from ordered snapshots", () => {
    expect(
      calculateNavChange([
        { date: "2026-06-01", nav: "100000" },
        { date: "2026-08-27", nav: "112500" },
      ]),
    ).toEqual({
      absolute: 12500,
      percent: 12.5,
      firstDate: "2026-06-01",
      lastDate: "2026-08-27",
    });
  });

  it("omits NAV change when history is insufficient or unusable", () => {
    expect(calculateNavChange([{ date: "2026-08-27", nav: "100000" }])).toBeNull();
    expect(
      calculateNavChange([
        { date: "2026-06-01", nav: "0" },
        { date: "2026-08-27", nav: "10" },
      ]),
    ).toBeNull();
    expect(
      calculateNavChange([
        { date: "2026-06-01", nav: "not-a-number" },
        { date: "2026-08-27", nav: "10" },
      ]),
    ).toBeNull();
  });

  it("derives portfolio weight only from usable display-currency values", () => {
    expect(calculatePortfolioWeight("250", "1000")).toBe(25);
    expect(calculatePortfolioWeight("250", "0")).toBeNull();
    expect(calculatePortfolioWeight("bad", "1000")).toBeNull();
  });

  it("joins projected dividends to the position native currency without guessing", () => {
    expect(currencyForProjectedDividend("7203.t", positions)).toBe("JPY");
    expect(currencyForProjectedDividend("UNKNOWN", positions)).toBeNull();
  });

  it("formats currencies, quantities, and signed percentages for financial scanning", () => {
    expect(formatCurrency("2800", "JPY")).toBe("¥2,800");
    expect(formatCurrency("128420.38", "USD")).toBe("$128,420.38");
    expect(formatCurrency(null, "USD")).toBe("—");
    expect(formatCurrency("10", "INVALID")).toBe("INVALID 10.00");
    expect(formatQuantity("0.000001")).toBe("0.000001");
    expect(formatQuantity("1000.000000")).toBe("1,000");
    expect(formatSignedPercent(12.5)).toBe("+12.50%");
    expect(formatSignedPercent(-8.725)).toBe("-8.73%");
    expect(formatSignedPercent(null)).toBe("—");
  });
});
