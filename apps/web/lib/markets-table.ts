/**
 * Sorting and formatting for the /markets table.
 *
 * Extracted from the page component so it can be unit-tested: the page itself
 * is an async server component that needs a live API to render.
 */

export type SortKey = "ticker" | "change" | "price";
export type SortDir = "asc" | "desc";

export type MarketRow = {
  ticker: string;
  name: string;
  sector: string | null;
  exchange: string | null;
  currency: string;
  closes: number[];
  last: number | null;
  changePct: number | null;
};

export function fmtPrice(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Price in the symbol's own trading currency — an NSE row is ₹, not $. */
export function fmtMoney(n: number | null, currency: string): string {
  if (n === null) return "—";
  const digits = currency === "JPY" ? 0 : 2;
  try {
    return n.toLocaleString("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  } catch {
    return `${currency} ${fmtPrice(n)}`;
  }
}

export function fmtPct(n: number | null): string {
  if (n === null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

/**
 * Sort a copy of `rows`. Symbols with no price data sort last in either
 * direction — a missing close is "unknown", not "worst", and burying it keeps
 * the top of the table meaningful.
 */
export function compare(rows: MarketRow[], sort: SortKey, dir: SortDir): MarketRow[] {
  const factor = dir === "asc" ? 1 : -1;

  const numeric =
    (pick: (r: MarketRow) => number | null) =>
    (a: MarketRow, b: MarketRow): number => {
      const av = pick(a);
      const bv = pick(b);
      if (av === null && bv === null) return a.ticker.localeCompare(b.ticker);
      if (av === null) return 1;
      if (bv === null) return -1;
      return (av - bv) * factor;
    };

  const sorter: Record<SortKey, (a: MarketRow, b: MarketRow) => number> = {
    ticker: (a, b) => a.ticker.localeCompare(b.ticker) * factor,
    change: numeric((r) => r.changePct),
    price: numeric((r) => r.last),
  };
  return [...rows].sort(sorter[sort]);
}

/** Which direction a header link should request when clicked. */
export function flipDir(current: SortKey | undefined, target: SortKey, dir: SortDir): SortDir {
  // First click on a new column: alphabetical ascending for ticker, but
  // "biggest first" for the numeric columns, which is what people expect.
  if (current !== target) return target === "ticker" ? "asc" : "desc";
  return dir === "asc" ? "desc" : "asc";
}

/** Build the href for a sortable column header, preserving the sector filter. */
export function sortHref(
  target: SortKey,
  params: { sort?: string; dir?: string; sector?: string },
): string {
  const next = new URLSearchParams();
  next.set("sort", target);
  next.set(
    "dir",
    flipDir(params.sort as SortKey | undefined, target, (params.dir as SortDir) ?? "desc"),
  );
  if (params.sector) next.set("sector", params.sector);
  return `/markets?${next.toString()}`;
}
