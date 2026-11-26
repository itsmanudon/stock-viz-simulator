/**
 * Volume profile (A6.7, M2.9), client-safe: the API's shape, the range a
 * chart asks for, and the pure geometry its primitive draws
 * (`lib/drawings/volume-profile-primitive.ts`).
 *
 * The API (`GET /v1/symbols/{t}/volume-profile`) builds the bins, the point
 * of control and the value area from stored minute bars when they cover the
 * range, else from daily bars ("EOD approximation"), spreading each bar's
 * volume evenly over its high-low range.
 *
 * - **Visible range:** the bars on screen, asked for again (debounced) when
 *   the chart is panned or zoomed. Drawn from the price pane's right edge.
 * - **Fixed range:** a `volume_profile` drawing's two sessions (A3.2's model),
 *   drawn between them.
 */

import type { components } from "@/lib/api/schema";
import { dateMs } from "@/lib/drawings/anchor";

export type VolumeProfile = components["schemas"]["VolumeProfileOut"];

export const PROFILE_MODES = [
  { value: "off", label: "Off" },
  { value: "visible", label: "Visible range" },
  { value: "fixed", label: "Fixed range" },
] as const;
export type ProfileMode = (typeof PROFILE_MODES)[number]["value"];

/** The URL parameter the toggle writes (client-side only; the server ignores it). */
export const PROFILE_PARAM = "vp";

export const PROFILE_DEBOUNCE_MS = 400;
export const PROFILE_BINS = 24;

export function parseProfileMode(raw: string | null | undefined): ProfileMode {
  return raw === "visible" || raw === "fixed" ? raw : "off";
}

export const PROFILE_SPREAD_NOTE =
  "Each bar's volume is spread evenly over its high-low range, so the profile is an approximation.";

type RangeBar = { ts: string; closed_at?: string | null };

const INTRADAY_TS = /T(?!00:00:00)/;

/**
 * The range (ISO instants) a run of bars covers, for the API: an intraday
 * bar from its open to just before its close; a daily (or weekly, monthly)
 * bar is its whole session date in UTC, which holds every venue's session.
 * Indices are clamped to the bars; null with no bars.
 */
export function rangeOfBars(
  bars: readonly RangeBar[],
  fromIndex: number,
  toIndex: number,
): { from: string; to: string } | null {
  if (bars.length === 0) return null;
  const lo = Math.max(0, Math.min(bars.length - 1, Math.floor(Math.min(fromIndex, toIndex))));
  const hi = Math.max(0, Math.min(bars.length - 1, Math.ceil(Math.max(fromIndex, toIndex))));
  const first = bars[lo];
  const last = bars[hi];
  const intraday = Boolean(last.closed_at) || INTRADAY_TS.test(last.ts);
  if (!intraday) {
    return { from: `${first.ts.slice(0, 10)}T00:00:00Z`, to: `${last.ts.slice(0, 10)}T23:59:59Z` };
  }
  const end = last.closed_at
    ? Date.parse(withZ(last.closed_at)) - 1000
    : Date.parse(withZ(last.ts));
  return { from: withZ(first.ts), to: new Date(end).toISOString().replace(".000Z", "Z") };
}

/** An API instant (naive = UTC) with its zone written out. */
function withZ(ts: string): string {
  return /[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`;
}

/** A fixed-range drawing's sessions as a range: whole days, earlier first. */
export function rangeOfSessions(a: string, b: string): { from: string; to: string } {
  const [lo, hi] = dateMs(a) <= dateMs(b) ? [a, b] : [b, a];
  return { from: `${lo.slice(0, 10)}T00:00:00Z`, to: `${hi.slice(0, 10)}T23:59:59Z` };
}

/** Run `fn` once calls stop for `ms`; `cancel` drops a pending call. */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): ((...args: A) => void) & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = (...args: A) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}

export type ProfileRect = {
  x: number;
  y: number;
  width: number;
  height: number;
  inValueArea: boolean;
  poc: boolean;
};

export type ProfileGeometry = {
  rects: ProfileRect[];
  /** Y of the POC price, VAH and VAL (null off the scale). */
  pocY: number | null;
  vahY: number | null;
  valY: number | null;
  /** Where the levels' lines run, left to right. */
  left: number;
  right: number;
};

/**
 * The bins as rectangles on the price pane. `anchor` is the x the bars grow
 * from and `side` the way they grow (`left` from the pane's right edge,
 * `right` from a fixed range's first session); the longest bin is
 * `maxWidth` px. A bin whose prices are off the scale is left out.
 */
export function profileGeometry(
  profile: Pick<VolumeProfile, "bins" | "poc" | "vah" | "val" | "poc_index" | "value_area">,
  yOfPrice: (price: number) => number | null,
  placement: { anchor: number; side: "left" | "right"; maxWidth: number },
  valueBins?: { low: number; high: number },
): ProfileGeometry {
  const most = Math.max(0, ...profile.bins.map((b) => b.volume));
  const val = Number(profile.val);
  const vah = Number(profile.vah);
  const area = valueBins ?? { low: val, high: vah };
  const rects: ProfileRect[] = [];
  profile.bins.forEach((bin, index) => {
    const yTop = yOfPrice(Number(bin.high));
    const yBottom = yOfPrice(Number(bin.low));
    if (yTop === null || yBottom === null || most <= 0) return;
    const width = (bin.volume / most) * placement.maxWidth;
    const top = Math.min(yTop, yBottom);
    // A pixel's gap between bins so neighbours read as separate bars.
    const height = Math.max(1, Math.abs(yBottom - yTop) - 1);
    rects.push({
      x: placement.side === "left" ? placement.anchor - width : placement.anchor,
      y: top,
      width,
      height,
      inValueArea: Number(bin.low) >= area.low && Number(bin.high) <= area.high,
      poc: index === profile.poc_index,
    });
  });
  const left = placement.side === "left" ? placement.anchor - placement.maxWidth : placement.anchor;
  return {
    rects,
    pocY: yOfPrice(Number(profile.poc)),
    vahY: yOfPrice(vah),
    valY: yOfPrice(val),
    left,
    right: left + placement.maxWidth,
  };
}

/** The badges and note in one line, for the chart's caption and screen readers. */
export function profileCaption(
  profile: Pick<VolumeProfile, "badges" | "poc" | "vah" | "val" | "value_area" | "note">,
): string {
  const pct = Math.round(profile.value_area * 100);
  return `Volume profile (${profile.badges.join(", ")}): point of control ${profile.poc}, value area (${pct}%) ${profile.val} to ${profile.vah}. ${profile.note}`;
}
