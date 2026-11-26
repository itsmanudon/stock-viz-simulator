/**
 * Moving drawings (A3.2): an anchor dragged to a new bar and price, or the
 * whole drawing shifted. Anchors stay bar dates (snapped to the bar under
 * the pointer, never past the last bar) and prices.
 */

import type { StockInterval } from "@/lib/stock-workspace";

import { anchorLogical, logicalToDate } from "./anchor";
import type { DrawingKind, DrawingPoint } from "./kinds";
import { kindSpec, pointForStep } from "./kinds";

/** A price from the chart, rounded for storage: 2 decimals, or 4 under 1. */
export function roundPrice(price: number): string {
  const digits = Math.abs(price) < 1 ? 4 : 2;
  const floor = 10 ** -digits;
  return Math.max(price, floor).toFixed(digits);
}

/** The anchor a chart position places for a kind's step. */
export function placePoint(
  kind: DrawingKind,
  step: number,
  at: { logical: number; price: number },
  barDates: readonly string[],
): DrawingPoint | null {
  const ts = logicalToDate(at.logical, barDates);
  if (ts === null) return null;
  return pointForStep(kind, step, { ts, price: roundPrice(at.price) });
}

export function dragPoints(
  kind: DrawingKind,
  points: readonly DrawingPoint[],
  handle: number | null,
  start: { logical: number; price: number },
  now: { logical: number; price: number },
  interval: StockInterval,
  barDates: readonly string[],
): DrawingPoint[] {
  if (handle !== null) {
    return points.map((p, i) => {
      if (i !== handle) return p;
      const placed = placePoint(kind, i, now, barDates);
      return placed ?? p;
    });
  }
  const dLogical = Math.round(now.logical - start.logical);
  const dPrice = now.price - start.price;
  const dateOnly = kindSpec(kind).dateOnly === true;
  return points.map((p) => {
    if (dateOnly && p.ts) {
      // An anchored VWAP moves in time only; its line follows the data.
      const logical = anchorLogical(p.ts, interval, barDates);
      const ts = logical === null ? p.ts : (logicalToDate(logical + dLogical, barDates) ?? p.ts);
      return { ts, price: "" };
    }
    const price = roundPrice(Number(p.price) + dPrice);
    if (!p.ts) return { ts: null, price };
    const logical = anchorLogical(p.ts, interval, barDates);
    const ts = logical === null ? p.ts : (logicalToDate(logical + dLogical, barDates) ?? p.ts);
    return { ts, price };
  });
}
