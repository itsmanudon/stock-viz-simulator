/**
 * Pure helpers for alert rules and notifications (Phase 7.3). Safe in the
 * browser: no server imports.
 */

export const NOTIFICATION_CATEGORIES = [
  { value: "", label: "All" },
  { value: "alert", label: "Alerts" },
  { value: "order", label: "Orders" },
  { value: "dividend", label: "Dividends" },
  { value: "corporate_action", label: "Splits" },
  { value: "option", label: "Options" },
] as const;

export function parseNotificationCategory(raw: string | undefined): string {
  return NOTIFICATION_CATEGORIES.some((c) => c.value === raw && raw) ? (raw as string) : "";
}

type RuleLike = {
  kind?: string;
  paused?: boolean;
  repeat?: string;
  triggered_at: string | null;
};

/** Active: watching now. Triggered: has fired. Paused shows under All only. */
export function matchesAlertView(alert: RuleLike, view: "active" | "triggered" | "all"): boolean {
  if (view === "all") return true;
  if (view === "triggered") return Boolean(alert.triggered_at);
  if (alert.paused) return false;
  return alert.repeat === "every_cross" || !alert.triggered_at;
}

/**
 * How far the close is from a price level, in % of the close: positive means
 * the price must rise to reach it. Null when either is missing.
 */
export function distanceToTargetPct(
  close: string | number | null | undefined,
  target: string | number | null | undefined,
): number | null {
  const c = Number(close);
  const t = Number(target);
  if (!close || !target || !Number.isFinite(c) || !Number.isFinite(t) || c <= 0) return null;
  return ((t - c) / c) * 100;
}

export type RuleDraft = {
  kind: "price" | "move" | "technical" | "news" | "portfolio";
  ticker: string;
  direction?: "above" | "below";
  target?: string;
  movePct?: string;
  indicator?: string;
  op?: "above" | "below";
  value?: string;
  compareTo?: string;
  sentiment?: string;
  eventType?: string;
  metric?: string;
  threshold?: string;
  repeat?: "once" | "every_cross";
};

const METRIC_LABEL: Record<string, string> = {
  drawdown_pct: "the account's drawdown from its peak",
  position_weight_pct: "a holding's share of the account",
  day_change_pct: "the account's move in a session",
};

/** The rule in words before it is saved (UX-2: a preview of what fires). */
export function previewRule(d: RuleDraft): string {
  const t = d.ticker || "the symbol";
  const again = d.repeat === "every_cross" ? ", every time it happens" : ", once";
  switch (d.kind) {
    case "price":
      return d.target
        ? `When ${t} closes ${d.direction ?? "above"} ${d.target}${again}.`
        : `Pick a target price for ${t}.`;
    case "move":
      return d.movePct
        ? `When ${t} closes ${d.movePct}% or more away from the previous close${again}.`
        : "Pick a move size in %.";
    case "technical": {
      const rhs = d.compareTo || d.value;
      return d.indicator && rhs
        ? `When ${t}'s ${d.indicator} crosses ${d.op ?? "above"} ${rhs}${again}.`
        : "Pick an indicator and what it crosses.";
    }
    case "news": {
      const mood = d.sentiment ? ` ${d.sentiment}` : "";
      const about = d.eventType ? ` about ${d.eventType}` : "";
      return `When new${mood} ${t} news${about} arrives from Aegis${again}.`;
    }
    case "portfolio":
      return d.metric && d.threshold
        ? `When ${METRIC_LABEL[d.metric] ?? d.metric} reaches ${d.threshold}%${again}.`
        : "Pick a portfolio measure and a threshold.";
  }
}
