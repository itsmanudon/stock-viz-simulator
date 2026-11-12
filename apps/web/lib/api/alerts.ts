import "server-only";

import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

export type AlertKind = "price" | "technical" | "news" | "portfolio";

/** One alert rule (Phase 7.1): its kind, settings and evaluation state. */
export type Alert = {
  id: number;
  /** Null only for portfolio rules. */
  ticker: string | null;
  kind?: AlertKind;
  /** Price-level rules only. */
  direction: "above" | "below" | null;
  target_price: string | null;
  params?: Record<string, unknown> | null;
  repeat?: "once" | "every_cross";
  cooldown_sessions?: number;
  paused?: boolean;
  created_at: string;
  armed_at?: string | null;
  triggered_at: string | null;
  dismissed_at: string | null;
  /** The condition at the last judged bar, and that bar's date. */
  last_state?: boolean | null;
  last_bar_date?: string | null;
  last_fired_bar_date?: string | null;
  /** The rule in words. Optional for responses cached before 7.1. */
  description?: string;
  /** The symbol's trading currency; target_price is in it. */
  currency?: string;
};

/** One firing of a rule: what was seen, against what, on which bar. */
export type AlertEvent = {
  id: number;
  alert_id: number;
  kind: string;
  ticker: string | null;
  session_date: string;
  bar_date: string | null;
  observed: string | null;
  threshold: string | null;
  message: string;
  source: string;
  created_at: string;
};

export type AlertInput = {
  ticker?: string | null;
  kind?: AlertKind;
  direction?: "above" | "below";
  target_price?: string;
  params?: Record<string, unknown>;
  repeat?: "once" | "every_cross";
  cooldown_sessions?: number;
};

export function listAlerts(): Promise<Alert[]> {
  return authedGet<Alert[]>("/v1/alerts");
}

export function listAlertEvents(limit = 100): Promise<AlertEvent[]> {
  return authedGet<AlertEvent[]>(`/v1/alerts/events?limit=${limit}`);
}

export function listRuleEvents(id: number): Promise<AlertEvent[]> {
  return authedGet<AlertEvent[]>(`/v1/alerts/${id}/events`);
}

export function createAlert(body: AlertInput): Promise<Alert> {
  return authedPost<Alert>("/v1/alerts", body);
}

export function deleteAlert(id: number): Promise<void> {
  return authedDelete(`/v1/alerts/${id}`);
}

export function dismissAlert(id: number): Promise<Alert> {
  return authedPost<Alert>(`/v1/alerts/${id}/dismiss`);
}

export function rearmAlert(id: number): Promise<Alert> {
  return authedPost<Alert>(`/v1/alerts/${id}/rearm`);
}

export function setAlertPaused(id: number, paused: boolean): Promise<Alert> {
  return authedPatch<Alert>(`/v1/alerts/${id}`, { paused });
}
