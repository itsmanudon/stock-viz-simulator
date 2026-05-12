import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";

export type Alert = {
  id: number;
  ticker: string;
  direction: "above" | "below";
  target_price: string;
  created_at: string;
  triggered_at: string | null;
  dismissed_at: string | null;
};

export type AlertInput = {
  ticker: string;
  direction: "above" | "below";
  target_price: string;
};

export function listAlerts(): Promise<Alert[]> {
  return authedGet<Alert[]>("/v1/alerts");
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
