/**
 * The footer's two live pieces (owner, 26 Nov 2026), both from stored data:
 *
 * - The close line: the equal-weight average of the terrain's symbols over
 *   their shared 120 sessions, ending in a champagne dot at the latest close.
 *   The page ends on the latest close, as the logo is one close. Its label
 *   states what it is, the window, the date and the move (gain or loss
 *   colour with an arrow and a sign, never colour alone).
 * - The status strip: symbols tracked, the newest stored close per market
 *   and the nightly refresh state, linking to /status.
 *
 * Each piece drops out on its own when its data is missing; neither ever
 * shows an invented figure.
 */

import Link from "next/link";

import { loadTerrain } from "@/components/prism/terrain-data";
import { ApiError, listSymbols } from "@/lib/api";
import { type ServiceStatus, getServiceStatusCached } from "@/lib/api/status";
import { equalWeightPath, lastPointY, linePath, statusFacts } from "@/lib/footer-market";

const W = 1000;
const H = 56;

async function safe<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch (err) {
    if (err instanceof ApiError || err instanceof TypeError) return null;
    throw err;
  }
}

/** The close line along the footer's top edge. */
export async function FooterCloseLine() {
  const terrain = await loadTerrain();
  const path = terrain ? equalWeightPath(terrain.series) : null;
  const move = path ? path[path.length - 1] : null;
  if (!path || !terrain || move === null) return null;
  return (
    <figure className="footer-close" data-testid="footer-close-line">
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Equal-weight average of ${terrain.tickers.length} tracked symbols over ${terrain.sessions} sessions to ${terrain.lastDate}: ${move >= 0 ? "up" : "down"} ${Math.abs(move).toFixed(1)}%`}
          className="block h-14 w-full overflow-visible"
        >
          <defs>
            <linearGradient id="footer-close-stroke" x1="0" x2="1">
              <stop offset="0" stopColor="var(--brand-gradient-from)" stopOpacity="0.15" />
              <stop offset="0.7" stopColor="var(--brand-gradient-to)" stopOpacity="0.7" />
              <stop offset="1" stopColor="var(--brand-gradient-via)" />
            </linearGradient>
          </defs>
          <path
            className="footer-close-line"
            d={linePath(path, W, H)}
            fill="none"
            stroke="url(#footer-close-stroke)"
            strokeWidth="1.5"
            pathLength={1}
          />
        </svg>
        {/* The end dot is HTML so it stays round under the stretched SVG. */}
        <span
          aria-hidden
          className="footer-close-dot"
          style={{ top: `${(lastPointY(path, H) / H) * 100}%` }}
        />
      </div>
      <figcaption className="mt-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-text-tertiary tabular-nums">
        <span>
          Equal-Weight Average · {terrain.tickers.length} Tracked Symbols · {terrain.sessions}{" "}
          Sessions
        </span>
        <span>
          Close of {terrain.lastDate}{" "}
          <span className={move >= 0 ? "text-positive" : "text-negative"}>
            {move >= 0 ? "▲ +" : "▼ −"}
            {Math.abs(move).toFixed(1)}%
          </span>
        </span>
      </figcaption>
    </figure>
  );
}

/** The status strip in the footer's bottom row. */
export async function FooterStatus() {
  const [status, symbols] = await Promise.all([
    safe<ServiceStatus>(getServiceStatusCached),
    safe(() => listSymbols()),
  ]);
  const facts = statusFacts(status);
  if (!symbols?.length && !facts.closes.length && facts.refresh === "unknown") return null;
  return (
    <Link
      href="/status"
      className="footer-status group flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-text-tertiary tabular-nums transition-colors hover:text-text-secondary"
      data-testid="footer-status"
    >
      {symbols?.length ? <span>{symbols.length} Symbols Tracked</span> : null}
      {facts.closes.map((close) => (
        <span key={close.market}>
          {close.market} Close {close.date}
        </span>
      ))}
      {facts.refresh !== "unknown" ? (
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className={`size-1.5 rounded-full ${facts.refresh === "ok" ? "bg-positive" : "bg-warning"}`}
          />
          {facts.refresh === "ok" ? "Nightly Refresh OK" : "Nightly Refresh Needs a Look"}
        </span>
      ) : null}
      <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
        →
      </span>
    </Link>
  );
}
