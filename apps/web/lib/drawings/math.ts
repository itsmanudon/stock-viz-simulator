/**
 * The arithmetic behind the drawing tools (A3.2): Fibonacci levels, the
 * measure ruler and the position tool. Pure; the renderer and the list share it.
 */

import { dateMs } from "./anchor";

export const FIB_RETRACEMENT = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
export const FIB_EXTENSION = [0, 0.618, 1, 1.272, 1.618, 2.618] as const;

export type FibLevel = { ratio: number; price: number; label: string };

function ratioLabel(ratio: number): string {
  return `${(ratio * 100).toFixed(1).replace(/\.0$/, "")}%`;
}

/**
 * Retracement levels between a swing from `start` to `end`: 0% at the end
 * (the swing's extreme), 100% back at the start.
 */
export function fibRetracement(start: number, end: number): FibLevel[] {
  return FIB_RETRACEMENT.map((ratio) => ({
    ratio,
    price: end - (end - start) * ratio,
    label: ratioLabel(ratio),
  }));
}

/** Extension levels: the swing a -> b projected from the retracement point c. */
export function fibExtension(a: number, b: number, c: number): FibLevel[] {
  return FIB_EXTENSION.map((ratio) => ({
    ratio,
    price: c + (b - a) * ratio,
    label: ratioLabel(ratio),
  }));
}

export type RulerStats = {
  deltaPrice: number;
  deltaPct: number;
  /** Bars between the two anchors on the chart's interval (signed). */
  bars: number;
  /** Calendar days between the two dates (signed). */
  days: number;
};

export function rulerStats(
  from: { date: string; price: number; logical: number },
  to: { date: string; price: number; logical: number },
): RulerStats {
  const deltaPrice = to.price - from.price;
  return {
    deltaPrice,
    deltaPct: from.price === 0 ? 0 : (deltaPrice / from.price) * 100,
    bars: Math.round(to.logical - from.logical),
    days: Math.round((dateMs(to.date) - dateMs(from.date)) / 86_400_000),
  };
}

export type PositionStats = {
  side: "long" | "short";
  riskPerShare: number;
  rewardPerShare: number;
  /** Reward over risk: the target is this many R from the entry. */
  rewardRisk: number;
  stopPct: number;
  targetPct: number;
  /** Whether stop and target sit on the right sides of the entry. */
  valid: boolean;
};

export function positionStats(
  side: "long" | "short",
  entry: number,
  stop: number,
  target: number,
): PositionStats {
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  const valid = side === "long" ? stop < entry && entry < target : target < entry && entry < stop;
  return {
    side,
    riskPerShare: risk,
    rewardPerShare: reward,
    rewardRisk: risk === 0 ? 0 : reward / risk,
    stopPct: entry === 0 ? 0 : ((stop - entry) / entry) * 100,
    targetPct: entry === 0 ? 0 : ((target - entry) / entry) * 100,
    valid,
  };
}

/** A price for a label: two decimals, or four under 1. */
export function formatPrice(value: number): string {
  return Math.abs(value) < 1 ? value.toFixed(4) : value.toFixed(2);
}

export function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}
