import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClickableRow } from "@/components/clickable-row";
import { CompareFundamentals } from "@/components/compare-fundamentals";
import type { Valuation } from "@/lib/api/fundamentals";
import { alignToSharedDates, parseCompareTickers } from "@/lib/compare-workspace";
import { activeFilterChips, screenerApiQuery } from "@/lib/screener-view";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

describe("RS-7: one shared window across markets", () => {
  it("keeps only the days every series traded", () => {
    const series = alignToSharedDates([
      { ticker: "AAPL", bars: [{ ts: "2026-11-09T00:00:00" }, { ts: "2026-11-10T00:00:00" }] },
      // An Indian holiday on 9 Nov: AAPL's 9 Nov bar drops out too.
      { ticker: "INFY.NS", bars: [{ ts: "2026-11-10T00:00:00" }, { ts: "2026-11-11T00:00:00" }] },
    ]);
    expect(series.map((s) => s.bars.map((b) => b.ts.slice(0, 10)))).toEqual([
      ["2026-11-10"],
      ["2026-11-10"],
    ]);
  });

  it("leaves a single series alone", () => {
    const one = [{ ticker: "AAPL", bars: [{ ts: "2026-11-09T00:00:00" }] }];
    expect(alignToSharedDates(one)).toBe(one);
  });

  it("reads the screener's repeated tickers params", () => {
    expect(parseCompareTickers(["aapl", "INFY.NS", "AAPL"])).toEqual(["AAPL", "INFY.NS"]);
  });
});

describe("Phase 6.5 screener fundamentals", () => {
  it("names the filters and sends the API its units", () => {
    const params = { pe_max: "20", mcap_min_bn: "10", roe_min: "15" };
    expect(activeFilterChips(params).map((c) => c.label)).toEqual([
      "P/E at most 20",
      "Market cap at least 10B USD",
      "ROE at least 15%",
    ]);
    const q = screenerApiQuery({ ...params, sort: "mcap", dir: "desc" }, 50);
    expect(q.get("market_cap_usd_min")).toBe("10000000000");
    expect(q.get("sort")).toBe("market_cap_usd");
  });

  it("does not open the stock page when the compare box is ticked", () => {
    push.mockReset();
    render(
      <table>
        <tbody>
          <ClickableRow href="/stocks/AAPL">
            <td>
              <input type="checkbox" aria-label="Compare AAPL" />
            </td>
            <td>AAPL</td>
          </ClickableRow>
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare AAPL" }));
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("AAPL"));
    expect(push).toHaveBeenCalledWith("/stocks/AAPL");
  });
});

describe("CompareFundamentals", () => {
  const val = (ticker: string, currency: string, pe: number | null): Valuation => ({
    ticker,
    as_of: "2026-11-12",
    trading_currency: currency === "USD" ? "USD" : "INR",
    reporting_currency: currency,
    basis: "ttm",
    point_in_time: false,
    sources: ["yfinance"],
    metrics: [
      { key: "pe", label: "P/E", value: pe, unit: "x", reason: pe === null ? "loss" : null },
      { key: "market_cap", label: "Market cap", value: 7.2e10, unit: currency, reason: null },
    ],
  });

  it("puts each company in its own column with its reporting currency", () => {
    render(
      <CompareFundamentals
        rows={[
          { ticker: "AAPL", valuation: val("AAPL", "USD", 30) },
          { ticker: "RELIANCE.NS", valuation: val("RELIANCE.NS", "INR", null) },
        ]}
      />,
    );
    expect(screen.getByText("reports in INR · not point-in-time")).toBeVisible();
    expect(screen.getByText("30.0×")).toBeVisible();
    expect(screen.getByText("INR 72B")).toBeVisible();
    expect(screen.getByTitle("loss")).toHaveTextContent("—");
  });
});
