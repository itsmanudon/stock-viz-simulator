import type { PortfolioHistoryPoint, Position } from "@/lib/api/trading";

export const PORTFOLIO_RANGES = [
  { value: "1m", label: "1M", days: 30 },
  { value: "3m", label: "3M", days: 90 },
  { value: "1y", label: "1Y", days: 365 },
  { value: "all", label: "All", days: null },
] as const;

/** Days of NAV history behind the dashboard hero sparkline. */
export const DASHBOARD_HISTORY_DAYS = 30;

export const PORTFOLIO_TABS = ["positions", "options", "orders", "income"] as const;

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
}: {
  range: PortfolioRange;
  tab: PortfolioTab;
}): string {
  const params = new URLSearchParams({ range });
  if (tab !== "positions") params.set("tab", tab);
  return `/portfolio?${params.toString()}`;
}

export function calculateNavChange(points: PortfolioHistoryPoint[]): NavChange | null {
  if (points.length < 2) return null;

  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  const first = Number(firstPoint.nav);
  const last = Number(lastPoint.nav);
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) return null;

  const absolute = last - first;
  return {
    absolute,
    percent: (absolute / first) * 100,
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

export function formatCurrency(raw: string | number | null, currency = "USD"): string {
  if (raw === null) return "—";
  const value = Number(raw);
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

export function formatQuantity(raw: string | number): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

export function formatSignedCurrency(raw: string | number | null, currency = "USD"): string {
  if (raw === null) return "—";
  const value = Number(raw);
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
