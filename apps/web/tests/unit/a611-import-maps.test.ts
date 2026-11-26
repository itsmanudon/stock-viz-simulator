/**
 * A6.11: the import page's map helpers (client-safe, lib/tradebook-import.ts):
 * the map choice as the API's query, the header row read in the browser,
 * the first guess and the checks of "Map columns yourself", the currency an
 * imported book is created in, and the Not Executed count.
 */

import { describe, expect, it } from "vitest";

import {
  brokerLabel,
  countItems,
  guessMapping,
  headerRowFromText,
  importQuery,
  importQueryString,
  importedBookCurrency,
  mappingProblem,
  marketZone,
  problemSkipsRow,
} from "@/lib/tradebook-import";

describe("A6.11 maps", () => {
  it("turns the map choice into the API's query", () => {
    expect(importQuery("auto")).toEqual({});
    expect(importQuery("dhan_tradebook_v1")).toEqual({ map: "dhan_tradebook_v1" });
    expect(importQuery("saved:12")).toEqual({ custom_map: 12 });
    expect(importQuery("saved:x")).toEqual({});
    expect(importQuery("Bad Map!")).toEqual({});
    expect(importQueryString("saved:3")).toBe("&custom_map=3");
    expect(importQueryString("auto")).toBe("");
  });

  it("reads a header row in the browser, quotes and BOM included", () => {
    expect(headerRowFromText('\uFEFFDate,"Symbol, Name",Qty\r\n1,2,3')).toEqual([
      "Date",
      "Symbol, Name",
      "Qty",
    ]);
    expect(headerRowFromText("\n\na;b;c\n")).toEqual(["a", "b", "c"]);
    expect(headerRowFromText("")).toEqual([]);
  });

  it("guesses a mapping, never one header twice", () => {
    const guess = guessMapping(["Date/Time", "Ticker", "Action", "Shares", "Price", "Fees"]);
    expect(guess).toEqual({
      executed_at: "Date/Time",
      symbol: "Ticker",
      side: "Action",
      quantity: "Shares",
      price: "Price",
    });
    expect(mappingProblem(guess)).toBeNull();
  });

  it("names what a mapping still needs, and a header used twice", () => {
    expect(mappingProblem({ symbol: "S" })).toBe(
      "Map these fields: Side (Buy or Sell), Quantity, Price, Trade Date or Execution Time",
    );
    expect(
      mappingProblem({ symbol: "S", side: "B", quantity: "Q", price: "Q", trade_date: "D" }),
    ).toMatch(/Quantity and Price read the same header/);
  });

  it("creates Indian broker books in INR and lets Other take the currency", () => {
    expect(importedBookCurrency("dhan", "USD")).toBe("INR");
    expect(importedBookCurrency("other", "USD")).toBe("USD");
    expect(brokerLabel("angelone")).toBe("Angel One");
    expect(brokerLabel("other")).toBe("Other Broker");
    expect(marketZone("us")).toEqual({ timeZone: "America/New_York", label: "ET" });
  });

  it("counts orders that did not execute", () => {
    const items = countItems({
      rows: 2,
      new: 1,
      posted: 1,
      needs_opening_lot: 0,
      duplicate: 0,
      unmatched: 0,
      skipped_segment: 0,
      rejected: 0,
      not_executed: 1,
      basis_uncertain: 0,
      intraday_inferred: 0,
    });
    expect(items).toContainEqual({ label: "Not Executed", value: 1 });
    expect(problemSkipsRow("not_executed")).toBe(true);
  });
});
