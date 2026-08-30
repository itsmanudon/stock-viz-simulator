import { describe, expect, it } from "vitest";

import {
  type MarketRow,
  compare,
  flipDir,
  fmtMoney,
  fmtPct,
  fmtPrice,
  sortHref,
} from "@/lib/markets-table";

function row(ticker: string, last: number | null, changePct: number | null): MarketRow {
  return {
    ticker,
    name: `${ticker} Co`,
    sector: null,
    exchange: null,
    currency: "USD",
    closes: [],
    last,
    changePct,
  };
}

describe("fmtPrice", () => {
  it("renders two decimals with thousands separators", () => {
    expect(fmtPrice(1234.5)).toBe("1,234.50");
    expect(fmtPrice(0)).toBe("0.00");
  });

  it("renders an em dash for missing data", () => {
    expect(fmtPrice(null)).toBe("—");
  });
});

describe("fmtMoney", () => {
  it("uses the symbol's own trading currency", () => {
    expect(fmtMoney(1234.5, "USD")).toBe("$1,234.50");
    expect(fmtMoney(1234.5, "INR")).toBe("₹1,234.50");
    expect(fmtMoney(1234, "JPY")).toBe("¥1,234");
  });

  it("falls back to a code prefix for a malformed currency", () => {
    // Intl.NumberFormat throws on a non-3-letter code; the catch path uses a
    // plain space, not Intl's non-breaking one.
    expect(fmtMoney(1234.5, "ZZ")).toBe("ZZ 1,234.50");
  });

  it("renders an em dash for missing data", () => {
    expect(fmtMoney(null, "INR")).toBe("—");
  });
});

describe("fmtPct", () => {
  it("signs positive values explicitly", () => {
    expect(fmtPct(2.345)).toBe("+2.35%");
    expect(fmtPct(-2.345)).toBe("-2.35%");
  });

  it("leaves zero unsigned", () => {
    expect(fmtPct(0)).toBe("0.00%");
  });

  it("renders an em dash for missing data", () => {
    expect(fmtPct(null)).toBe("—");
  });
});

describe("compare", () => {
  const rows = [row("BBB", 50, -1.5), row("AAA", 100, 2.5), row("CCC", 75, 0.5)];

  it("sorts by ticker in both directions", () => {
    expect(compare(rows, "ticker", "asc").map((r) => r.ticker)).toEqual(["AAA", "BBB", "CCC"]);
    expect(compare(rows, "ticker", "desc").map((r) => r.ticker)).toEqual(["CCC", "BBB", "AAA"]);
  });

  it("sorts by price and by change", () => {
    expect(compare(rows, "price", "desc").map((r) => r.ticker)).toEqual(["AAA", "CCC", "BBB"]);
    expect(compare(rows, "change", "asc").map((r) => r.ticker)).toEqual(["BBB", "CCC", "AAA"]);
  });

  it("does not mutate the input array", () => {
    const original = [...rows];
    compare(rows, "price", "desc");
    expect(rows).toEqual(original);
  });

  it("sorts rows with no data last regardless of direction", () => {
    // A newly listed symbol with no bars is "unknown", not "worst" — putting it
    // at the top of a descending sort would be actively misleading.
    const withGaps = [row("AAA", 100, 2.5), row("NEW", null, null), row("BBB", 50, -1.5)];
    expect(compare(withGaps, "price", "desc").map((r) => r.ticker)).toEqual(["AAA", "BBB", "NEW"]);
    expect(compare(withGaps, "price", "asc").map((r) => r.ticker)).toEqual(["BBB", "AAA", "NEW"]);
  });
});

describe("flipDir", () => {
  it("defaults a new numeric column to descending", () => {
    expect(flipDir("ticker", "price", "asc")).toBe("desc");
    expect(flipDir("ticker", "change", "asc")).toBe("desc");
  });

  it("defaults a new ticker column to ascending", () => {
    expect(flipDir("price", "ticker", "desc")).toBe("asc");
  });

  it("toggles when the column is already active", () => {
    expect(flipDir("price", "price", "desc")).toBe("asc");
    expect(flipDir("price", "price", "asc")).toBe("desc");
  });
});

describe("sortHref", () => {
  it("builds a sort link", () => {
    expect(sortHref("price", {})).toBe("/markets?sort=price&dir=desc");
  });

  it("preserves the active sector filter", () => {
    const href = sortHref("price", { sector: "Technology" });
    expect(href).toContain("sector=Technology");
    expect(href).toContain("sort=price");
  });

  it("url-encodes a sector containing a space", () => {
    expect(sortHref("ticker", { sector: "Consumer Staples" })).toContain("sector=Consumer+Staples");
  });
});
