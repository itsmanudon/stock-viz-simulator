import { formatCurrency } from "@/lib/portfolio-view-model";

export const ORDER_TYPES = ["limit", "stop_loss", "take_profit"] as const;
export const ORDER_STATUSES = ["pending", "filled", "cancelled"] as const;
export const ORDER_STATUS_FILTERS = ["pending", "filled", "cancelled", "all"] as const;
export const TRADE_ORDER_MODES = ["market", "limit", "stop_loss", "take_profit"] as const;
export const ALERT_VIEWS = ["active", "triggered", "all"] as const;

export type OrderType = (typeof ORDER_TYPES)[number];
export type OrderStatus = (typeof ORDER_STATUSES)[number];
export type OrderStatusFilter = (typeof ORDER_STATUS_FILTERS)[number];
export type TradeOrderMode = (typeof TRADE_ORDER_MODES)[number];
export type AlertView = (typeof ALERT_VIEWS)[number];

export const OPERATIONAL_SUBNAV = [
  { href: "/trade", label: "Trade ticket" },
  { href: "/orders", label: "Orders" },
] as const;

export const MONITORING_SUBNAV = [
  { href: "/watchlist", label: "Watchlist" },
  { href: "/alerts", label: "Alerts" },
] as const;

export function parseTradeTicker(raw: string | undefined): string {
  const ticker = raw?.trim().toUpperCase() ?? "";
  if (!ticker || ticker.length > 16) return "";
  return ticker;
}

export function buildTradeHref(ticker?: string): string {
  if (!ticker) return "/trade";
  return `/trade?ticker=${encodeURIComponent(ticker)}`;
}

export function parseOrdersStatus(raw: string | undefined): OrderStatusFilter {
  return ORDER_STATUS_FILTERS.includes(raw as OrderStatusFilter)
    ? (raw as OrderStatusFilter)
    : "pending";
}

export function buildOrdersHref(status: OrderStatusFilter): string {
  if (status === "pending") return "/orders";
  return `/orders?status=${status}`;
}

export function parseAlertView(raw: string | undefined): AlertView {
  return ALERT_VIEWS.includes(raw as AlertView) ? (raw as AlertView) : "active";
}

export function parseAlertTicker(raw: string | undefined): string {
  return parseTradeTicker(raw);
}

export function buildAlertsHref({
  view,
  ticker,
}: {
  view?: AlertView;
  ticker?: string;
} = {}): string {
  const params = new URLSearchParams();
  if (view && view !== "active") params.set("view", view);
  if (ticker) params.set("ticker", ticker);
  const qs = params.toString();
  return qs ? `/alerts?${qs}` : "/alerts";
}

export function orderTypeLabel(type: string): string {
  switch (type) {
    case "market":
      return "Market";
    case "limit":
      return "Limit";
    case "stop_loss":
      return "Stop-loss";
    case "take_profit":
      return "Take-profit";
    default:
      return type;
  }
}

export function orderStatusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "Pending";
    case "filled":
      return "Filled";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

export function alertDirectionLabel(direction: "above" | "below"): string {
  return direction === "above" ? "At or above" : "At or below";
}

export function userCancelReason(reason: string | null | undefined): string {
  const trimmed = reason?.trim();
  if (trimmed) return trimmed;
  return "Cancelled by user";
}

export function currencyByTicker(
  symbols: Iterable<{ ticker: string; currency?: string | null }>,
): Record<string, string> {
  const currencies: Record<string, string> = {};
  for (const symbol of symbols) {
    const code = symbol.currency?.trim();
    currencies[symbol.ticker.trim().toUpperCase()] = code || "USD";
  }
  return currencies;
}

export function tickerCurrency(ticker: string, currencies: Record<string, string>): string {
  return currencies[ticker.trim().toUpperCase()] ?? "USD";
}

export function formatNativePrice(
  amount: string | number | null,
  ticker: string,
  currencies: Record<string, string>,
): string {
  return formatCurrency(amount, tickerCurrency(ticker, currencies));
}

export function dayMovePct(
  firstClose: number | undefined,
  lastClose: number | undefined,
): number | null {
  if (
    firstClose === undefined ||
    lastClose === undefined ||
    !Number.isFinite(firstClose) ||
    !Number.isFinite(lastClose) ||
    firstClose === 0
  ) {
    return null;
  }
  return ((lastClose - firstClose) / firstClose) * 100;
}
