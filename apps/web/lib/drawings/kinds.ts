/**
 * Chart drawing kinds (A3.2, M2.4): what each kind is called, how many
 * anchors it takes and what each click places. The API holds the same rules
 * (`apps/api/src/stockviz/services/drawings.py`).
 */

import type { components } from "@/lib/api/schema";

export type Drawing = components["schemas"]["DrawingOut"];
export type DrawingKind = Drawing["kind"];
export type DrawingStyle = components["schemas"]["DrawingStyle"];
export type DrawingColour = DrawingStyle["colour"];
/** An anchor: a daily bar's venue date (YYYY-MM-DD) and a price string. */
export type DrawingPoint = { ts: string | null; price: string };
export type DrawingsResponse = components["schemas"]["DrawingsOut"];

export type KindSpec = {
  kind: DrawingKind;
  label: string;
  /** Anchors the API takes. */
  points: number;
  /** What each click places, in order. */
  steps: string[];
  /** Anchors after the first that are prices only (no date). */
  priceOnlyFrom?: number;
};

export const KIND_SPECS: readonly KindSpec[] = [
  { kind: "trendline", label: "Trend line", points: 2, steps: ["start", "end"] },
  { kind: "ray", label: "Ray", points: 2, steps: ["start", "a point it passes"] },
  { kind: "hline", label: "Horizontal line", points: 1, steps: ["the price"] },
  { kind: "rectangle", label: "Rectangle", points: 2, steps: ["one corner", "the other corner"] },
  {
    kind: "channel",
    label: "Parallel channel",
    points: 3,
    steps: ["start", "end", "the parallel side"],
  },
  {
    kind: "fib_retracement",
    label: "Fib retracement",
    points: 2,
    steps: ["swing start", "swing end"],
  },
  {
    kind: "fib_extension",
    label: "Fib extension",
    points: 3,
    steps: ["swing start", "swing end", "the retracement"],
  },
  { kind: "ruler", label: "Measure", points: 2, steps: ["from", "to"] },
  { kind: "text", label: "Text note", points: 1, steps: ["where the note goes"] },
  {
    kind: "position_long",
    label: "Long position",
    points: 3,
    steps: ["entry", "stop", "target"],
    priceOnlyFrom: 1,
  },
  {
    kind: "position_short",
    label: "Short position",
    points: 3,
    steps: ["entry", "stop", "target"],
    priceOnlyFrom: 1,
  },
];

const BY_KIND = new Map(KIND_SPECS.map((s) => [s.kind, s]));

export function kindSpec(kind: DrawingKind): KindSpec {
  const spec = BY_KIND.get(kind);
  if (!spec) throw new Error(`unknown drawing kind ${kind}`);
  return spec;
}

export const DRAWING_COLOURS: readonly DrawingColour[] = [
  "aqua",
  "blue",
  "violet",
  "pink",
  "amber",
  "lime",
  "slate",
  "foreground",
];

export const DEFAULT_STYLE: DrawingStyle = {
  colour: "aqua",
  width: 1,
  dash: "solid",
  fill_opacity: 0.12,
};

/** A click's point for a kind: dates are dropped where the kind takes prices only. */
export function pointForStep(kind: DrawingKind, step: number, point: DrawingPoint): DrawingPoint {
  const spec = kindSpec(kind);
  if (kind === "hline") return { ts: null, price: point.price };
  if (spec.priceOnlyFrom !== undefined && step >= spec.priceOnlyFrom) {
    return { ts: null, price: point.price };
  }
  return point;
}

/** A short description of a drawing for the list ("Trend line, 10 Mar 2025 100.50 to ..."). */
export function describeDrawing(drawing: Pick<Drawing, "kind" | "points" | "label">): string {
  const spec = kindSpec(drawing.kind);
  const at = (p: DrawingPoint) => (p.ts ? `${p.price} on ${p.ts}` : p.price);
  const points = toPoints(drawing.points);
  let body: string;
  if (drawing.kind === "hline") body = `at ${points[0]?.price}`;
  else if (drawing.kind === "position_long" || drawing.kind === "position_short") {
    body = `entry ${at(points[0])}, stop ${points[1]?.price}, target ${points[2]?.price}`;
  } else if (points.length === 1) body = `at ${at(points[0])}`;
  else body = points.map(at).join(" to ");
  return `${spec.label}${drawing.label ? ` "${drawing.label}"` : ""}, ${body}`;
}

/** A saved drawing's points with `ts` always present (the API may omit a null). */
export function toPoints(points: Drawing["points"]): DrawingPoint[] {
  return points.map((p) => ({ ts: p.ts ?? null, price: p.price }));
}
