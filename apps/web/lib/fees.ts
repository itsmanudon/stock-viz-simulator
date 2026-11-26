/**
 * A4.2 (M7.2): costs. Date-versioned fee schedules, each component citing the
 * document its rate was copied from (`GET /v1/fees/schedules`), a run's
 * `costs` disclosure and the order review's estimate (`GET /v1/fees/estimate`).
 * Browser-safe: types from the API schema and pure helpers only.
 */

import type { components } from "./api/schema";

export type CostsOut = components["schemas"]["CostsOut"];
export type LiquidityOut = components["schemas"]["LiquidityOut"];
export type FeeVersion = components["schemas"]["FeeVersionOut"];
export type FeeComponent = components["schemas"]["FeeComponentOut"];
export type FeeSource = components["schemas"]["FeeSourceOut"];
export type FeeScheduleInfo = components["schemas"]["FeeScheduleOut"];
export type FeeSchedules = components["schemas"]["FeeSchedulesOut"];
export type FeeEstimate = components["schemas"]["FeeEstimateOut"];
export type FeeScheduleName = NonNullable<components["schemas"]["BacktestIn"]["fee_schedule"]>;
export type BrokerageName = NonNullable<components["schemas"]["BacktestIn"]["brokerage"]>;

/** The schedules a backtest can choose (cash equity on daily bars). */
export const FEE_SCHEDULE_OPTIONS: { value: FeeScheduleName; label: string }[] = [
  { value: "auto", label: "Automatic (by market)" },
  { value: "none", label: "None" },
  { value: "us_equity", label: "US equity (SEC, FINRA on sales)" },
  { value: "in_equity_delivery_nse", label: "India delivery, NSE (STT, stamp, GST, DP)" },
  { value: "in_equity_delivery_bse", label: "India delivery, BSE (STT, stamp, GST, DP)" },
];

export const BROKERAGE_OPTIONS: { value: BrokerageName; label: string }[] = [
  { value: "zerodha", label: "Zerodha plan" },
  { value: "zero", label: "No brokerage" },
];

export const DEFAULT_ADV_CAP_PCT = "10";

const SIDE_LABEL: Record<FeeComponent["side"], string> = {
  buy: "Buys",
  sell: "Sells",
  both: "Both sides",
};

export function sideLabel(side: FeeComponent["side"]): string {
  return SIDE_LABEL[side];
}

/** "In force 1 Oct 2024 to 28 Feb 2026" / "In force from 1 Apr 2026". */
export function versionRange(
  v: Pick<FeeVersion, "effective_from" | "effective_to"> & { start_confirmed?: boolean },
): string {
  if (v.start_confirmed === false && v.effective_to) {
    return `up to ${formatDay(v.effective_to)} (start date not confirmed)`;
  }
  const from = formatDay(v.effective_from);
  return v.effective_to ? `${from} to ${formatDay(v.effective_to)}` : `from ${from}`;
}

/** Whether `v` is in force on `day` (ISO date). */
export function inForce(
  v: Pick<FeeVersion, "effective_from" | "effective_to">,
  day: string,
): boolean {
  return (
    v.effective_from <= day &&
    (v.effective_to === null || v.effective_to === undefined || day <= v.effective_to)
  );
}

export function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** "Document dated 31 Mar 2026, read 26 Nov 2026" (or "Undated page, ..."). */
export function sourceDated(source: FeeSource): string {
  const dated = /^\d{4}-\d{2}-\d{2}$/.test(source.date)
    ? `dated ${formatDay(source.date)}`
    : /^\d{4}-\d{2}$/.test(source.date)
      ? `dated ${source.date}`
      : source.date;
  return `${dated}, read ${formatDay(source.read_on)}`;
}

/** "partial: 100 of 1,000 shares", or null when the cap did not bind. */
export function partialLabel(
  filled: string | number,
  requested: string | number | null | undefined,
): string | null {
  if (requested === null || requested === undefined) return null;
  const fmt = (n: string | number) =>
    Number(n).toLocaleString("en-US", { maximumFractionDigits: 4 });
  return `partial: ${fmt(filled)} of ${fmt(requested)} shares`;
}

/** The ADV-cap field: empty or 0 turns the cap off (null). */
export function advCapValue(raw: string): number | null {
  const n = Number(raw);
  return raw.trim() === "" || !Number.isFinite(n) || n <= 0 ? null : Math.min(n, 100);
}

/** " · fees ₹63.10 · paid ₹25,063.10" after a fill, or "" when none were charged. */
export function feesSuffix(
  success: {
    side: "buy" | "sell";
    fees?: string | null;
    net_native?: string | null;
    currency: string;
  },
  money: (value: number, currency: string) => string,
): string {
  if (!success.fees || Number(success.fees) === 0 || !success.net_native) return "";
  const net = money(Number(success.net_native), success.currency);
  return ` · fees ${money(Number(success.fees), success.currency)} · ${success.side === "buy" ? "paid" : "received"} ${net}`;
}
