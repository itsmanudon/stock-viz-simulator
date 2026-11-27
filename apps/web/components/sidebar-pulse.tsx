/**
 * The sidebar's market pulse (inside redesign, 27 Nov 2026): the same close
 * line the public footer ends on, so the workspace and the landing page share
 * one picture of the market. The equal-weight average of the terrain's
 * symbols over their shared 120 sessions, a champagne dot at the latest
 * close, and the move in text with a sign and an arrow (never colour alone).
 *
 * An async server component from stored data only. It renders nothing when
 * the terrain has too few aligned symbols, so it never shows an invented
 * figure. Unit tests that render the shell mock this module.
 */

import Link from "next/link";

import { loadTerrain } from "@/components/prism/terrain-data";
import { equalWeightPath, lastPointY, linePath } from "@/lib/footer-market";

const W = 200;
const H = 40;

export async function SidebarPulse() {
  const terrain = await loadTerrain().catch(() => null);
  const path = terrain ? equalWeightPath(terrain.series) : null;
  const move = path ? path[path.length - 1] : null;
  if (!terrain || !path || move === null) return null;
  const up = move >= 0;
  return (
    <Link
      href="/markets"
      className="sidebar-pulse group block rounded-lg border border-border-muted bg-card/60 px-3 pt-2.5 pb-2 transition-colors hover:border-border hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      data-testid="sidebar-pulse"
      aria-label={`Market pulse: equal-weight average of ${terrain.tickers.length} tracked symbols over ${terrain.sessions} sessions to ${terrain.lastDate}, ${up ? "up" : "down"} ${Math.abs(move).toFixed(1)}%. Open Markets`}
    >
      <span className="flex items-baseline justify-between gap-2 text-2xs">
        <span className="font-medium tracking-[0.02em] text-text-secondary">Market Pulse</span>
        <span className={`font-mono ${up ? "text-positive" : "text-negative"}`}>
          {up ? "▲ +" : "▼ −"}
          {Math.abs(move).toFixed(1)}%
        </span>
      </span>
      <span aria-hidden className="relative mt-1.5 block">
        <svg
          aria-hidden="true"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="block h-10 w-full overflow-visible"
        >
          <defs>
            <linearGradient id="sidebar-pulse-stroke" x1="0" x2="1">
              <stop offset="0" stopColor="var(--brand-gradient-from)" stopOpacity="0.2" />
              <stop offset="0.7" stopColor="var(--brand-gradient-to)" stopOpacity="0.75" />
              <stop offset="1" stopColor="var(--brand-gradient-via)" />
            </linearGradient>
            <linearGradient id="sidebar-pulse-fill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--brand-gradient-via)" stopOpacity="0.14" />
              <stop offset="1" stopColor="var(--brand-gradient-via)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            d={`${linePath(path, W, H)} L ${W} ${H} L 0 ${H} Z`}
            fill="url(#sidebar-pulse-fill)"
          />
          <path
            className="sidebar-pulse-line"
            d={linePath(path, W, H)}
            fill="none"
            stroke="url(#sidebar-pulse-stroke)"
            strokeWidth="1.25"
            vectorEffect="non-scaling-stroke"
            pathLength={1}
          />
        </svg>
        <span className="footer-close-dot" style={{ top: `${(lastPointY(path, H) / H) * 100}%` }} />
      </span>
      <span className="mt-1.5 flex items-baseline justify-between gap-2 font-mono text-3xs text-text-tertiary">
        <span>
          {terrain.tickers.length} Symbols · {terrain.sessions}d
        </span>
        <span>{terrain.lastDate}</span>
      </span>
    </Link>
  );
}
