/**
 * A4.5: the scan event study page (`/event-study`). Pure helpers: the URL
 * (shareable: `rule` or `setup`, `tickers` | `market` | `watchlist`,
 * `from`, `to`, `cooldown`) parsed into a request, links into the page, the
 * trigger presets and the words for a figure. Browser-safe.
 */

import type { components } from "./api/schema";

export type ScanStudyRequest = components["schemas"]["ScanEventStudyIn"];
export type ScanStudy = components["schemas"]["ScanEventStudyOut"];
export type ScanHorizon = components["schemas"]["ScanHorizonOut"];

export type TriggerPreset = { group: "news" | "delivery"; label: string; rule: string };

/** News and delivery triggers are rules too; these are the common ones. */
export const TRIGGER_PRESETS: TriggerPreset[] = [
  { group: "news", label: "Any news that day", rule: "news.count(1) >= 1" },
  {
    group: "news",
    label: "Negative news that day",
    rule: 'news.count(1, sentiment="negative") >= 1',
  },
  {
    group: "news",
    label: "Positive news that day",
    rule: 'news.count(1, sentiment="positive") >= 1',
  },
  { group: "delivery", label: "Delivery above 60%", rule: "delivery_pct > 60" },
  {
    group: "delivery",
    label: "Delivery 1.5x its 20-day average",
    rule: "delivery_pct > 1.5 * sma(delivery_pct, 20)",
  },
];

export const DEFAULT_TRIGGER = "close crosses_above sma(close, 50)";

export type StudyParams = {
  rule?: string | string[];
  setup?: string;
  tickers?: string | string[];
  market?: string;
  watchlist?: string;
  from?: string;
  to?: string;
  cooldown?: string;
};

export type ParsedStudy = {
  rule: string;
  setup: number | null;
  universe: "market" | "tickers" | "watchlist";
  market: "US" | "IN";
  tickers: string[];
  watchlist: number | null;
  from: string;
  to: string;
  cooldown: number;
};

const ISO = /^\d{4}-\d{2}-\d{2}$/;

function first(raw: string | string[] | undefined): string {
  return (Array.isArray(raw) ? raw[0] : raw) ?? "";
}

function positiveInt(raw: string | undefined): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function parseStudyParams(params: StudyParams): ParsedStudy {
  const raw = Array.isArray(params.tickers)
    ? params.tickers
    : params.tickers
      ? [params.tickers]
      : [];
  const tickers = [
    ...new Set(
      raw
        .flatMap((t) => t.split(/[\s,;]+/))
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  ].slice(0, 50);
  const watchlist = positiveInt(params.watchlist);
  const cooldown = Number(params.cooldown);
  return {
    rule: first(params.rule).slice(0, 4000),
    setup: positiveInt(params.setup),
    universe: watchlist ? "watchlist" : tickers.length ? "tickers" : "market",
    market: params.market === "IN" ? "IN" : "US",
    tickers,
    watchlist,
    from: ISO.test(params.from ?? "") ? (params.from as string) : "",
    to: ISO.test(params.to ?? "") ? (params.to as string) : "",
    cooldown: Number.isInteger(cooldown) && cooldown >= 0 && cooldown <= 250 ? cooldown : 0,
  };
}

/** The request, or null when the URL names no trigger yet. */
export function studyRequest(p: ParsedStudy): ScanStudyRequest | null {
  if (!p.rule.trim() && p.setup === null) return null;
  const universe: ScanStudyRequest["universe"] =
    p.universe === "watchlist" && p.watchlist
      ? { watchlist_id: p.watchlist }
      : p.universe === "tickers"
        ? { tickers: p.tickers }
        : { market: p.market };
  return {
    trigger: p.setup !== null ? { setup_version_id: p.setup } : { rule: p.rule.trim() },
    universe,
    from: p.from || null,
    to: p.to || null,
    cooldown: p.cooldown,
  };
}

/** A link to /event-study (from the screener's rule panel or a setup). */
export function eventStudyHref(opts: {
  rule?: string;
  setup?: number;
  market?: "US" | "IN";
  tickers?: string[];
}): string {
  const q = new URLSearchParams();
  if (opts.setup) q.set("setup", String(opts.setup));
  else if (opts.rule) q.set("rule", opts.rule);
  if (opts.tickers?.length) q.set("tickers", opts.tickers.join(","));
  else if (opts.market) q.set("market", opts.market);
  const qs = q.toString();
  return qs ? `/event-study?${qs}` : "/event-study";
}

/** A fraction as a signed percent: 0.0123 -> "+1.23%". */
export function signedPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "–";
  const v = value * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** A share as a percent: 0.56 -> "56.0%". */
export function sharePct(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${(value * 100).toFixed(1)}%`;
}

export function tStat(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : value.toFixed(2);
}
