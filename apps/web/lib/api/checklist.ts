import { apiGet } from "./client";
import type { Checklist, SymbolChecklist } from "./types";

export type ChecklistParams = {
  minMet?: number;
  dimension?: string;
  sort?: "met" | "ticker";
  limit?: number;
  /** Opt into the Next data cache; scores are recomputed by the nightly `checklist` job. */
  revalidateSeconds?: number;
};

/** A2.4: every active symbol's latest six-dimension checklist (public). */
export function getChecklist(params: ChecklistParams = {}): Promise<Checklist> {
  const q = new URLSearchParams();
  if (params.minMet !== undefined) q.set("min_met", String(params.minMet));
  if (params.dimension) q.set("dimension", params.dimension);
  if (params.sort) q.set("sort", params.sort);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  const qs = q.toString();
  return apiGet<Checklist>(
    `/v1/checklist${qs ? `?${qs}` : ""}`,
    params.revalidateSeconds === undefined
      ? undefined
      : { revalidateSeconds: params.revalidateSeconds, tags: ["checklist"] },
  );
}

/** One symbol's latest checklist with every dimension's formula and grade. */
export function getSymbolChecklist(ticker: string): Promise<SymbolChecklist> {
  return apiGet<SymbolChecklist>(`/v1/symbols/${encodeURIComponent(ticker)}/checklist`);
}
