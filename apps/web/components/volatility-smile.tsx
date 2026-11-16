"use client";

/**
 * Implied volatility by strike for the latest stored option chain (Phase
 * 9.6): one line per expiry, each strike drawn from the out-of-the-money
 * contract (puts below today's close, calls above), the usual way to read a
 * smile. Plain SVG; the snapshot date and source are written beside it.
 */

import { useEffect, useState } from "react";

import { type OptionSurface, getOptionSurface } from "@/lib/api/option-quote";

const W = 480;
const H = 160;
const DASHES = ["", "6 4", "2 3", "10 3 2 3"];

export function smilePoints(
  surface: OptionSurface,
): { expiry: string; points: [number, number][] }[] {
  const spot = Number(surface.spot ?? 0);
  return surface.expiries.map((e) => ({
    expiry: e.expiry,
    points: e.points
      .map((p): [number, number | null] => {
        const k = Number(p.strike);
        const iv = k < spot ? (p.put_iv ?? p.call_iv) : (p.call_iv ?? p.put_iv);
        return [k, iv];
      })
      .filter((p): p is [number, number] => p[1] !== null),
  }));
}

export function VolatilitySmile({ ticker }: { ticker: string }) {
  const [surface, setSurface] = useState<OptionSurface | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    const controller = new AbortController();
    setFailed(false);
    getOptionSurface(ticker, controller.signal)
      .then(setSurface)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [ticker]);

  if (failed) return null;
  if (!surface) return null;
  if (!surface.snapshot_date) {
    return (
      <p className="text-xs text-text-tertiary">
        No option chain is stored for {ticker} yet, so its options are priced on 30-day historical
        volatility.
      </p>
    );
  }
  const lines = smilePoints(surface).filter((l) => l.points.length > 1);
  if (lines.length === 0) return null;
  const all = lines.flatMap((l) => l.points);
  const x0 = Math.min(...all.map((p) => p[0]));
  const x1 = Math.max(...all.map((p) => p[0]));
  const y0 = Math.min(...all.map((p) => p[1]));
  const y1 = Math.max(...all.map((p) => p[1]));
  const x = (v: number) => ((v - x0) / (x1 - x0 || 1)) * W;
  const y = (v: number) => H - ((v - y0) / (y1 - y0 || 1)) * H;
  return (
    <figure aria-label={`Volatility smile for ${ticker}`} className="space-y-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-36 w-full overflow-visible" aria-hidden="true">
        {lines.map((line, i) => (
          <path
            key={line.expiry}
            d={line.points
              .map(([k, iv], j) => `${j === 0 ? "M" : "L"}${x(k).toFixed(1)},${y(iv).toFixed(1)}`)
              .join(" ")}
            fill="none"
            className="stroke-brand"
            strokeWidth={1.5}
            strokeDasharray={DASHES[i % DASHES.length]}
          />
        ))}
      </svg>
      <figcaption className="text-2xs text-text-tertiary">
        Implied volatility by strike ({(y0 * 100).toFixed(0)}% to {(y1 * 100).toFixed(0)}%), strikes{" "}
        {x0} to {x1}, from the {surface.snapshot_date} chain:{" "}
        {lines.map((l) => l.expiry).join(", ")}. {surface.source}.
      </figcaption>
    </figure>
  );
}
