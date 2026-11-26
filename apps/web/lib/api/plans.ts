import "server-only";

/**
 * `/v1/plans` (A5.4, M10.3): trade plans, private to the user. Types and the
 * ticket helpers are client-safe in `lib/plans.ts`.
 */

import type { BookRef } from "@/lib/book-url";
import type {
  PlanSetupOption,
  PlanThesisOption,
  TradePlan,
  TradePlanInput,
  TradePlanPatch,
  TradePlans,
} from "@/lib/plans";

import { withBook } from "./books";
import { authedDelete, authedGet, authedPatch, authedPost } from "./server";
import { listSetups } from "./setups-server";

export type PlanFilters = {
  status?: TradePlan["status"];
  source?: TradePlan["source"];
  setupVersionId?: number;
  /** A6.7: one ticker's plans (the chart's plan lines). */
  ticker?: string;
};

/** One book's plans (a numeric book), or every plan of the user (null). */
export function listPlans(book?: BookRef | null, filters: PlanFilters = {}): Promise<TradePlans> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.setupVersionId) params.set("setup_version_id", String(filters.setupVersionId));
  if (filters.ticker) params.set("ticker", filters.ticker);
  const qs = params.toString();
  return authedGet<TradePlans>(
    withBook(`/v1/plans${qs ? `?${qs}` : ""}`, book === "all" ? null : book),
  );
}

export function createPlan(body: TradePlanInput, book?: number | null): Promise<TradePlan> {
  return authedPost<TradePlan>(withBook("/v1/plans", book), body);
}

export function updatePlan(id: number, body: TradePlanPatch): Promise<TradePlan> {
  return authedPatch<TradePlan>(`/v1/plans/${id}`, body);
}

export function deletePlan(id: number): Promise<void> {
  return authedDelete(`/v1/plans/${id}`);
}

type ThesisRow = { id: number; ticker: string | null; title: string; status: string };

/** The ticket's pickers: your setups (and presets) and your open theses. */
export async function planPickerOptions(): Promise<{
  setups: PlanSetupOption[];
  theses: PlanThesisOption[];
}> {
  const [setups, theses] = await Promise.all([
    listSetups().catch(() => []),
    authedGet<ThesisRow[]>("/v1/theses?status=open").catch(() => [] as ThesisRow[]),
  ]);
  return {
    setups: setups
      .filter((s) => s.kind !== "checklist")
      .map((s) => ({
        versionId: s.latest_version.id,
        label: `${s.name} v${s.latest_version.version}${s.is_preset ? " (preset)" : ""}`,
      })),
    theses: theses.map((t) => ({ id: t.id, ticker: t.ticker, title: t.title })),
  };
}
