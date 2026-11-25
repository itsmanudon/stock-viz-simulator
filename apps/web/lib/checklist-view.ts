/**
 * Pure helpers for the Checklist (A2.4): URL state, wording, and which
 * dimension setup (formula and grade) judged a symbol.
 *
 * Wording is neutral on purpose: "4 of 6 met", "met", "not met", "unknown".
 * The Checklist counts published conditions; it never says buy or sell.
 */

import type {
  ChecklistDimension,
  ChecklistEvidence,
  ChecklistResult,
  ChecklistRow,
  ChecklistStatus,
  ChecklistVariant,
} from "@/lib/api/types";

export const CHECKLIST_TOTAL = 6;

export type ChecklistSort = "met" | "ticker";

export type ChecklistSearchParams = {
  min?: string;
  dimension?: string;
  sort?: string;
  q?: string;
};

export const STATUS_LABEL: Record<ChecklistStatus, string> = {
  met: "Met",
  not_met: "Not met",
  unknown: "Unknown",
};

export function statusTone(status: ChecklistStatus): "positive" | "neutral" | "warning" {
  if (status === "met") return "positive";
  if (status === "unknown") return "warning";
  return "neutral";
}

export function parseMinMet(raw: string | undefined): number {
  const n = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(CHECKLIST_TOTAL, n));
}

export function parseDimension(
  raw: string | undefined,
  keys: readonly string[],
): string | undefined {
  const value = raw?.trim().toLowerCase();
  return value && keys.includes(value) ? value : undefined;
}

export function parseChecklistSort(raw: string | undefined): ChecklistSort {
  return raw === "ticker" ? "ticker" : "met";
}

export function buildChecklistHref(state: {
  min?: number;
  dimension?: string;
  sort?: ChecklistSort;
  q?: string;
}): string {
  const q = new URLSearchParams();
  if (state.min && state.min > 0) q.set("min", String(state.min));
  if (state.dimension) q.set("dimension", state.dimension);
  if (state.sort && state.sort !== "met") q.set("sort", state.sort);
  if (state.q) q.set("q", state.q);
  const qs = q.toString();
  return qs ? `/checklist?${qs}` : "/checklist";
}

/** Rows matching a ticker or name search, sorted (most met first, or by ticker). */
export function filterChecklistRows(
  rows: readonly ChecklistRow[],
  { query, sort }: { query?: string; sort: ChecklistSort },
): ChecklistRow[] {
  const needle = query?.trim().toLowerCase();
  const kept = needle
    ? rows.filter(
        (row) =>
          row.ticker.toLowerCase().includes(needle) || row.name.toLowerCase().includes(needle),
      )
    : [...rows];
  if (sort === "ticker") return kept.sort((a, b) => a.ticker.localeCompare(b.ticker));
  return kept.sort(
    (a, b) => b.met - a.met || b.evaluated - a.evaluated || a.ticker.localeCompare(b.ticker),
  );
}

/** "4 of 6 met" — the one summary the page and the stock panel use. */
export function metSummary(row: Pick<ChecklistRow, "met" | "total">): string {
  return `${row.met} of ${row.total} met`;
}

export function evaluatedNote(row: Pick<ChecklistRow, "evaluated" | "total">): string {
  const unknown = row.total - row.evaluated;
  return unknown > 0 ? `${row.evaluated} judged, ${unknown} unknown` : `all ${row.total} judged`;
}

/** The dimension setup that judged ``result``: by its version, else by scope. */
export function variantFor(
  dimension: ChecklistDimension,
  result: Pick<ChecklistResult, "scope" | "setup_version_id"> | undefined,
): ChecklistVariant | undefined {
  if (!result) return dimension.variants[0];
  return (
    dimension.variants.find((v) => v.setup_version_id === result.setup_version_id) ??
    dimension.variants.find((v) => v.scope === result.scope) ??
    dimension.variants[0]
  );
}

export function resultFor(row: ChecklistRow, key: string): ChecklistResult | undefined {
  return row.results.find((result) => result.key === key);
}

export const SCOPE_LABEL: Record<ChecklistVariant["scope"], string> = {
  all: "All listings",
  india: "NSE and BSE listings",
  other: "Listings outside India",
};

export function gradeLabel(evidence: ChecklistEvidence | null | undefined): string {
  if (!evidence) return "Not graded yet";
  if (evidence.grade === "insufficient") return "Too few events to grade";
  return `Grade ${evidence.grade}`;
}

function percent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const pct = value * 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

/** The sample a grade was measured on, in one line. */
export function evidenceSample(evidence: ChecklistEvidence): string {
  return `${evidence.n_events} events over ${evidence.symbols} symbols, ${evidence.window_start} to ${evidence.window_end}, ${evidence.horizon} sessions after each`;
}

export function evidenceFigures(evidence: ChecklistEvidence): string {
  const t =
    evidence.t_stat === null || evidence.t_stat === undefined ? "—" : evidence.t_stat.toFixed(2);
  const hit =
    evidence.hit_rate === null || evidence.hit_rate === undefined
      ? "—"
      : `${Math.round(evidence.hit_rate * 100)}%`;
  return `Mean excess after fees ${percent(evidence.mean_excess)}, t ${t}, above the base rate ${hit} of the time`;
}

export const GRADE_BANDS =
  "A: t ≥ 3 and mean excess ≥ 1%. B: t ≥ 2. C: t ≥ 1. D: otherwise. Under 30 events: not graded.";
