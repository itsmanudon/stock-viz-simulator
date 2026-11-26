/**
 * A4.7 (M9.3): drills and decks. Types from the API schema and pure helpers
 * for the launch form, the deck list and the drill view.
 */

import type { components } from "@/lib/api/schema";

export type DrillDeckRequest = components["schemas"]["DrillDeckIn"];
export type DrillDeck = components["schemas"]["DrillDeckOut"];
export type DrillRow = components["schemas"]["DrillRowOut"];
export type DrillView = components["schemas"]["DrillOut"];
export type DrillPlan = components["schemas"]["DrillPlanOut"];
export type DrillPlanInput = components["schemas"]["DrillPlanIn"];
export type DrillScore = components["schemas"]["DrillScoreOut"];
export type DrillReveal = components["schemas"]["DrillRevealOut"];
export type DrillStatus = DrillRow["status"];

export const DRILL_K = { min: 1, max: 25, default: 10 } as const;
export const DRILL_LEAD = { min: 5, max: 250, default: 60 } as const;
export const DRILL_FOLLOW = { min: 5, max: 250, default: 40 } as const;

export const DRILL_STATUS_LABEL: Record<DrillStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  revealed: "Revealed",
};

export type LaunchUniverse = "market" | "tickers" | "watchlist";

/** What a link into `/drills/new` carries (`drillLaunchHref`). */
export type LaunchParams = {
  rule?: string;
  setupVersionId?: number;
  market?: "US" | "IN";
  tickers?: string[];
  watchlistId?: number;
  from?: string;
  to?: string;
};

/** `/drills/new?...`: the launch form prefilled from an entry point. */
export function drillLaunchHref(p: LaunchParams): string {
  const q = new URLSearchParams();
  if (p.setupVersionId) q.set("setup_version_id", String(p.setupVersionId));
  else if (p.rule) q.set("rule", p.rule);
  if (p.watchlistId) q.set("watchlist_id", String(p.watchlistId));
  else if (p.tickers?.length) q.set("tickers", p.tickers.join(","));
  else if (p.market) q.set("market", p.market);
  if (p.from) q.set("from", p.from);
  if (p.to) q.set("to", p.to);
  const qs = q.toString();
  return qs ? `/drills/new?${qs}` : "/drills/new";
}

export type LaunchForm = {
  name: string;
  rule: string;
  setupVersionId: string;
  universe: LaunchUniverse;
  market: "US" | "IN";
  tickers: string;
  watchlistId: string;
  from: string;
  to: string;
  k: string;
  lead: string;
  follow: string;
  seed: string;
  anonymised: boolean;
};

function intIn(raw: string, lo: number, hi: number): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const n = Number(raw);
  return n >= lo && n <= hi ? n : null;
}

/** Why the form cannot be sent, or null. */
export function launchProblem(f: LaunchForm): string | null {
  if (!f.setupVersionId && !f.rule.trim()) return "Enter a rule or pick a setup.";
  if (f.universe === "tickers" && !parseTickers(f.tickers).length)
    return "List at least one ticker.";
  if (f.universe === "tickers" && parseTickers(f.tickers).length > 50) return "At most 50 tickers.";
  if (f.universe === "watchlist" && !f.watchlistId) return "Pick a watchlist.";
  if (intIn(f.k, DRILL_K.min, DRILL_K.max) === null) return "K is a whole number from 1 to 25.";
  if (intIn(f.lead, DRILL_LEAD.min, DRILL_LEAD.max) === null) return "Lead-in is 5 to 250 bars.";
  if (intIn(f.follow, DRILL_FOLLOW.min, DRILL_FOLLOW.max) === null)
    return "Bars after the trigger are 5 to 250.";
  if (f.seed.trim() && intIn(f.seed, 0, 2 ** 31 - 1) === null)
    return "The seed is a whole number (or leave it empty).";
  if (f.from && f.to && f.from > f.to) return "'From' must be on or before 'to'.";
  return null;
}

export function parseTickers(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  ];
}

/** The API body for a valid form (call `launchProblem` first). */
export function buildDeckRequest(f: LaunchForm): DrillDeckRequest {
  const universe: DrillDeckRequest["universe"] =
    f.universe === "watchlist"
      ? { watchlist_id: Number(f.watchlistId) }
      : f.universe === "tickers"
        ? { tickers: parseTickers(f.tickers) }
        : { market: f.market };
  return {
    name: f.name.trim() || null,
    rule: f.setupVersionId
      ? { setup_version_id: Number(f.setupVersionId) }
      : { rule: f.rule.trim() },
    universe,
    from: f.from || null,
    to: f.to || null,
    k: Number(f.k),
    lead_bars: Number(f.lead),
    follow_bars: Number(f.follow),
    seed: f.seed.trim() ? Number(f.seed) : null,
    anonymised: f.anonymised,
  };
}

/** "2 of 3 checks", or "No trade" / "—". */
export function scoreLabel(score: DrillScore | null | undefined): string {
  if (!score) return "—";
  if (!score.traded) return "No trade";
  return `${score.passed} of ${score.applicable} check${score.applicable === 1 ? "" : "s"}`;
}

export function deckScoreLine(summary: DrillDeck["summary"]): string {
  if (summary.revealed === 0) return "No drill revealed yet";
  const checks =
    summary.checks_applicable > 0
      ? `${summary.checks_passed} of ${summary.checks_applicable} checks passed`
      : "no checks applied";
  return `${summary.followed_plan} of ${summary.traded} traded drills followed the plan · ${checks}`;
}

/** Planned risk and the share of cash it puts at risk. */
export function planRisk(entry: number, stop: number, size: number): number | null {
  if (!(entry > 0) || !(stop > 0) || !(size > 0) || stop >= entry) return null;
  return (entry - stop) * size;
}

export function universeLabel(u: Record<string, unknown>): string {
  const name = typeof u.source_name === "string" ? u.source_name : null;
  if (typeof u.market === "string") return name ?? `${u.market} market`;
  if (Array.isArray(u.tickers)) return `${u.tickers.length} tickers`;
  if (u.watchlist_id !== undefined) return name ? `Watchlist ${name}` : "A watchlist";
  return "—";
}
