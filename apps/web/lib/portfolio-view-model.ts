import type { PortfolioHistoryPoint, Position } from "@/lib/api/trading";

export const PORTFOLIO_RANGES = [
  { value: "1m", label: "1M", days: 30 },
  { value: "3m", label: "3M", days: 90 },
  { value: "1y", label: "1Y", days: 365 },
  { value: "all", label: "All", days: null },
] as const;

/** Days of NAV history behind the dashboard hero sparkline. */
export const DASHBOARD_HISTORY_DAYS = 30;

export const PORTFOLIO_TABS = [
  "positions",
  "options",
  "orders",
  "income",
  "news",
  "journal",
  "analytics",
] as const;

export type PortfolioRange = (typeof PORTFOLIO_RANGES)[number]["value"];
export type PortfolioTab = (typeof PORTFOLIO_TABS)[number];

export type NavChange = {
  absolute: number;
  percent: number;
  firstDate: string;
  lastDate: string;
};

export function parsePortfolioRange(raw: string | undefined): PortfolioRange {
  return PORTFOLIO_RANGES.some((range) => range.value === raw) ? (raw as PortfolioRange) : "3m";
}

export function parsePortfolioTab(raw: string | undefined): PortfolioTab {
  return PORTFOLIO_TABS.includes(raw as PortfolioTab) ? (raw as PortfolioTab) : "positions";
}

export function portfolioRangeDays(range: PortfolioRange): number | null {
  const selected = PORTFOLIO_RANGES.find((candidate) => candidate.value === range);
  return selected ? selected.days : 90;
}

export function buildPortfolioHref({
  range,
  tab,
  month,
  book,
}: {
  range: PortfolioRange;
  tab: PortfolioTab;
  /** Journal month (`YYYY-MM`). Ignored on the other tabs, which don't have one. */
  month?: string;
  /** A5.2: the selected book (`?book=`), kept on every tab and range link. */
  book?: number | "all" | null;
}): string {
  const params = new URLSearchParams({ range });
  if (tab !== "positions") params.set("tab", tab);
  if (tab === "journal" && month) params.set("month", month);
  if (book != null) params.set("book", String(book));
  return `/portfolio?${params.toString()}`;
}

/**
 * The change over a series. A5.2: All books points carry `flow`, the outside
 * money that day (a new book, an imported buy). It is left out of the
 * change, and the percent is the time-weighted return over the points, so
 * opening a book never reads as a gain. Without flows this is last - first.
 */
export function calculateNavChange(points: PortfolioHistoryPoint[]): NavChange | null {
  if (points.length < 2) return null;

  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  const first = Number(firstPoint.nav);
  const last = Number(lastPoint.nav);
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) return null;

  const flows = points.slice(1).map((p) => Number(p.flow ?? 0));
  if (flows.every((f) => f === 0)) {
    const absolute = last - first;
    return {
      absolute,
      percent: (absolute / first) * 100,
      firstDate: firstPoint.date,
      lastDate: lastPoint.date,
    };
  }
  let growth = 1;
  for (let i = 1; i < points.length; i++) {
    const prev = Number(points[i - 1].nav);
    const curr = Number(points[i].nav);
    if (!(prev > 0) || !Number.isFinite(curr)) return null;
    growth *= (curr - flows[i - 1]) / prev;
  }
  return {
    absolute: last - first - flows.reduce((sum, f) => sum + f, 0),
    percent: (growth - 1) * 100,
    firstDate: firstPoint.date,
    lastDate: lastPoint.date,
  };
}

export function calculatePortfolioWeight(
  positionValue: string | number,
  totalValue: string | number,
): number | null {
  const position = Number(positionValue);
  const total = Number(totalValue);
  if (!Number.isFinite(position) || !Number.isFinite(total) || total === 0) return null;
  return (position / total) * 100;
}

export function currencyForProjectedDividend(ticker: string, positions: Position[]): string | null {
  const position = positions.find(
    (candidate) => candidate.ticker.toUpperCase() === ticker.toUpperCase(),
  );
  return position?.currency || null;
}

/**
 * An amount rounded to the precision it is shown at (whole yen, else cents),
 * with negative zero folded to zero. Sign, tone and the formatted figure all
 * use this, so a -0.000001 from the API reads as $0.00, not a red "-$0.00".
 */
export function displayedAmount(raw: string | number, currency = "USD"): number {
  const value = Number(raw);
  if (!Number.isFinite(value)) return value;
  const scale = currency === "JPY" ? 1 : 100;
  // Halves round away from zero, as toLocaleString does, so the sign and
  // tone always agree with the printed figure (Math.round sends -0.5 to -0).
  const rounded = (Math.sign(value) * Math.round(Math.abs(value) * scale)) / scale;
  return rounded === 0 ? 0 : rounded;
}

export function formatCurrency(raw: string | number | null, currency = "USD"): string {
  if (raw === null) return "—";
  const value = displayedAmount(raw, currency);
  if (!Number.isFinite(value)) return "—";

  const fractionDigits = currency === "JPY" ? 0 : 2;
  try {
    return value.toLocaleString("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    });
  } catch {
    return `${currency} ${value.toFixed(fractionDigits)}`;
  }
}

/**
 * Splits a formatted amount into its whole units and its minor units
 * ("$20,000.00" → ["$20,000", ".00"]) so a headline figure can dim the cents.
 * Currencies formatted without decimals return `null` for the minor part.
 */
export function splitMinorUnits(formatted: string): [major: string, minor: string | null] {
  const match = /^(.*?)(\.\d+)$/.exec(formatted);
  return match ? [match[1], match[2]] : [formatted, null];
}

export function formatQuantity(raw: string | number): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function formatSignedCurrency(raw: string | number | null, currency = "USD"): string {
  if (raw === null) return "—";
  const value = displayedAmount(raw, currency);
  if (!Number.isFinite(value)) return "—";
  const formatted = formatCurrency(value, currency);
  return value > 0 ? `+${formatted}` : formatted;
}

export function formatSignedPercent(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  const formatted = value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return `${sign}${formatted}%`;
}

/**
 * The API files holdings without sector metadata under "Unknown" (sector and
 * exchange come from `stockviz.cli metadata`, which needs network). Name that
 * bucket plainly, and say when it is the whole book: a single "Unknown 100%"
 * bar looks like a fact about the portfolio, not missing data (UI audit D3).
 */
export const UNCLASSIFIED_SECTOR = "Unknown";

export function sectorLabel(sector: string): string {
  return sector === UNCLASSIFIED_SECTOR ? "Sector not recorded" : sector;
}

export function allocationIsUnclassified(slices: { sector: string }[]): boolean {
  return slices.length > 0 && slices.every((slice) => slice.sector === UNCLASSIFIED_SECTOR);
}

export const UNCLASSIFIED_ALLOCATION_NOTE =
  "Sector data has not been recorded for these holdings yet, so the allocation cannot be split by sector.";
