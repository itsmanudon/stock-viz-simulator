import "server-only";

import { authedGet } from "./server";
import type { EarningsEvent } from "./types";

export type EarningsScope = "all" | "holdings" | "watchlist";

export type EarningsCalendarParams = {
  from: string;
  to: string;
  scope?: EarningsScope;
};

export function getEarningsCalendar(params: EarningsCalendarParams): Promise<EarningsEvent[]> {
  const query = new URLSearchParams({ from: params.from, to: params.to });
  if (params.scope && params.scope !== "all") query.set("scope", params.scope);
  return authedGet<EarningsEvent[]>(`/v1/earnings?${query.toString()}`);
}
