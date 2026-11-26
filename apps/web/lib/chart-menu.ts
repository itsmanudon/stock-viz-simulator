/**
 * Chart-native alerts and trade planning (A6.7, M2.11), client-safe and pure:
 * what each item of the price pane's context menu sends.
 *
 * Every alert item builds the **same form fields** the alert form posts
 * (`components/alert-form.tsx`), so it goes through the same server action
 * (`createAlertAction`) and creates the same rule:
 *
 * - "Alert when price crosses here": a price alert at the crosshair price,
 *   `above` when that is over the last close, else `below`.
 * - "Alert on this indicator": a technical alert, the close crossing the
 *   hovered overlay study (`compare_to`), towards it from where it is.
 * - "Alert on this drawing": a Rule DSL setup reading the drawing (A3.3's
 *   bindings, `drawing("label").price`, `.top`/`.bottom`, `avwap("label")`),
 *   then a rule alert on that setup version. The drawing needs a label.
 * - "Plan a trade here": the plan editor's figures (long): entry at the
 *   crosshair, the stop at the nearest drawing level below it (else 2 x
 *   ATR(14), at the last bar, below), the target at the nearest level above it (else 2R).
 */

import type { IndicatorPoint } from "@/lib/api/types";
import { roundPrice } from "@/lib/drawings/drag";
import type { SceneDrawing } from "@/lib/drawings/scene";

export type AlertFields = Record<string, string>;

/** Rules are judged on stored bars; only A6.5's stream worker judges them as bars close. */
export function judgedNote(streaming: boolean): string {
  return streaming
    ? "A stream is running, so an intraday rule on this symbol is judged as each bar closes; price and indicator alerts are judged on the next stored daily bar."
    : "Alerts are judged on the next stored bar, not in real time: no stream is running.";
}

export function priceAlertFields(ticker: string, price: number, lastClose: number): AlertFields {
  return {
    kind: "price",
    ticker,
    direction: price >= lastClose ? "above" : "below",
    target_price: roundPrice(price),
    repeat: "once",
  };
}

/** The close crossing `studyKey` (an overlay key, e.g. `sma_50` or `bb_20_2.upper`). */
export function studyAlertFields(
  ticker: string,
  studyKey: string,
  studyValue: number,
  lastClose: number,
): AlertFields {
  return {
    kind: "technical",
    ticker,
    indicator: "close",
    op: lastClose <= studyValue ? "above" : "below",
    compare_to: studyKey,
    repeat: "once",
  };
}

export function ruleAlertFields(ticker: string, setupVersionId: number): AlertFields {
  return { kind: "rule", ticker, setup_version_id: String(setupVersionId), repeat: "once" };
}

export function toFormData(fields: AlertFields): FormData {
  const form = new FormData();
  for (const [name, value] of Object.entries(fields)) form.set(name, value);
  return form;
}

const LINE_KINDS = new Set(["hline", "trendline", "ray"]);
const RULE_KINDS = "horizontal lines, trend lines, rays, rectangles and anchored VWAPs";

export type DrawingRule = { rule: string; name: string; words: string } | { problem: string };

/**
 * The Rule DSL text for an alert on a drawing, crossing towards it from the
 * last close (`near`: the drawing's price where it was clicked, for a line).
 */
export function drawingRule(
  drawing: Pick<SceneDrawing, "kind" | "label" | "points">,
  ticker: string,
  lastClose: number,
  near: number,
): DrawingRule {
  const label = drawing.label?.trim() ?? "";
  if (drawing.kind !== "avwap" && !LINE_KINDS.has(drawing.kind) && drawing.kind !== "rectangle") {
    return { problem: `Rules can read ${RULE_KINDS}, not this drawing.` };
  }
  if (!label) {
    return { problem: "Label the drawing first (in the Drawings list), so the rule can name it." };
  }
  if (label.includes('"'))
    return { problem: "A label with a double quote can't be named in a rule." };
  const ref = `"${label}"`;
  let rule: string;
  let words: string;
  if (drawing.kind === "rectangle") {
    const prices = drawing.points.map((p) => Number(p.price)).filter(Number.isFinite);
    const top = Math.max(...prices);
    const bottom = Math.min(...prices);
    if (lastClose > top) {
      rule = `close crosses_below drawing(${ref}).top`;
      words = `closes back below the top of "${label}"`;
    } else {
      rule =
        lastClose < bottom
          ? `close crosses_above drawing(${ref}).bottom`
          : `close crosses_above drawing(${ref}).top`;
      words =
        lastClose < bottom
          ? `closes above the bottom of "${label}"`
          : `closes above the top of "${label}"`;
    }
  } else {
    const up = lastClose < near;
    const series = drawing.kind === "avwap" ? `avwap(${ref})` : `drawing(${ref}).price`;
    rule = `close ${up ? "crosses_above" : "crosses_below"} ${series}`;
    words = `closes ${up ? "above" : "below"} "${label}"`;
  }
  return { rule, name: `${ticker}: ${words}`.slice(0, 120), words };
}

/** The overlay study nearest the pointer at bar `ts`, within `maxPx`, or null. */
export function nearestStudy(
  overlays: Record<string, readonly IndicatorPoint[]>,
  ts: string,
  y: number,
  yOfPrice: (price: number) => number | null,
  maxPx = 24,
): { key: string; value: number } | null {
  let best: { key: string; value: number; distance: number } | null = null;
  for (const [key, points] of Object.entries(overlays)) {
    const point = points.find((p) => p.ts === ts);
    if (!point || !Number.isFinite(point.value)) continue;
    const at = yOfPrice(point.value);
    if (at === null) continue;
    const distance = Math.abs(at - y);
    if (distance <= maxPx && (!best || distance < best.distance)) {
      best = { key, value: point.value, distance };
    }
  }
  return best ? { key: best.key, value: best.value } : null;
}

type OhlcBar = { high: string | number; low: string | number; close: string | number };

/** The average true range over the `period` bars up to `index` (simple mean), or null. */
export function atrAt(bars: readonly OhlcBar[], index: number, period = 14): number | null {
  if (index < 1 || index >= bars.length) return null;
  const from = Math.max(1, index - period + 1);
  let sum = 0;
  let n = 0;
  for (let i = from; i <= index; i++) {
    const high = Number(bars[i].high);
    const low = Number(bars[i].low);
    const prev = Number(bars[i - 1].close);
    sum += Math.max(high - low, Math.abs(high - prev), Math.abs(low - prev));
    n += 1;
  }
  return n ? sum / n : null;
}

/** Price levels a drawing marks, for the plan's stop and target. */
export function drawingLevels(
  drawings: readonly Pick<SceneDrawing, "id" | "kind" | "points">[],
): number[] {
  const kinds = new Set([
    "hline",
    "trendline",
    "ray",
    "rectangle",
    "position_long",
    "position_short",
    "channel",
  ]);
  return drawings
    .filter((d) => d.id !== "draft" && kinds.has(d.kind))
    .flatMap((d) => d.points.map((p) => Number(p.price)))
    .filter((n) => Number.isFinite(n) && n > 0);
}

export type PlanPrefill = {
  entry: string;
  stop: string;
  target: string;
  /** Where the stop and target came from, in words. */
  stopFrom: "drawing" | "atr" | "none";
  targetFrom: "drawing" | "2r" | "none";
};

/** A long plan's figures from the crosshair (see the module rules). */
export function planPrefill(
  entry: number,
  levels: readonly number[],
  atr: number | null,
): PlanPrefill {
  const below = levels.filter((l) => l < entry).sort((a, b) => b - a)[0];
  const above = levels.filter((l) => l > entry).sort((a, b) => a - b)[0];
  let stop: number | null = null;
  let stopFrom: PlanPrefill["stopFrom"] = "none";
  if (below !== undefined) {
    stop = below;
    stopFrom = "drawing";
  } else if (atr !== null && atr > 0 && entry - 2 * atr > 0) {
    stop = entry - 2 * atr;
    stopFrom = "atr";
  }
  let target: number | null = null;
  let targetFrom: PlanPrefill["targetFrom"] = "none";
  if (above !== undefined) {
    target = above;
    targetFrom = "drawing";
  } else if (stop !== null) {
    target = entry + 2 * (entry - stop);
    targetFrom = "2r";
  }
  return {
    entry: roundPrice(entry),
    stop: stop === null ? "" : roundPrice(stop),
    target: target === null ? "" : roundPrice(target),
    stopFrom,
    targetFrom,
  };
}
