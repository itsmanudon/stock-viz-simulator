/**
 * Full-bleed marquee strip under the hero.
 *
 * Replaces the old "Today's movers" card grid. Same data, same graceful
 * degradation — a symbol with no stored bars renders a "—" rather than
 * dropping out, so the strip keeps its width on a freshly seeded database.
 *
 * The track holds the row twice because `.marquee-track` wraps at -50%; the
 * second copy is `aria-hidden` so the tickers are announced once. Under
 * `prefers-reduced-motion` the stylesheet drops the animation and turns the
 * strip into a normal horizontal scroller.
 *
 * Each half is `min-w-[100vw]` with `justify-around`. That is what makes the
 * wrap seamless at *any* viewport: a half narrower than the screen would leave
 * the -50% translate short and open a visible gap, and the server can't
 * measure the viewport to decide how many copies to emit. Stretching the gaps
 * instead is correct at every width, and only shows on displays wider than the
 * natural row.
 *
 * It has to be `100vw`, NOT `min-w-full`. A percentage min-width inside a
 * `width: max-content` track is a cyclic dependency: the track then sizes its
 * box to one half (offsetWidth 4447 against scrollWidth 8895) and `-50%` moves
 * a quarter of the content, so the loop visibly jumps. A viewport unit doesn't
 * depend on the parent, so the track sizes to both halves correctly.
 */

import Link from "next/link";

import { ApiError, getBars, listSymbols } from "@/lib/api";

/** Leads the strip; the rest of the row is filled from the live universe. */
const PREFERRED = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM"];

/** Enough distinct symbols to fill a wide display without visible repetition. */
const MAX_TICKERS = 14;

type Row = {
  ticker: string;
  close: number | null;
  changePct: number | null;
};

async function loadRow(ticker: string): Promise<Row> {
  try {
    const bars = await getBars(ticker, { limit: 2 });
    if (bars.length === 0) return { ticker, close: null, changePct: null };
    const close = Number(bars[bars.length - 1].close);
    const prev = bars.length > 1 ? Number(bars[bars.length - 2].close) : null;
    const changePct = prev !== null && prev !== 0 ? ((close - prev) / prev) * 100 : null;
    return { ticker, close, changePct };
  } catch (err) {
    if (err instanceof ApiError) return { ticker, close: null, changePct: null };
    throw err;
  }
}

function fmtPrice(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n: number | null): string {
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function TickerItem({ row }: { row: Row }) {
  const tone =
    row.changePct === null
      ? "text-text-tertiary"
      : row.changePct >= 0
        ? "text-positive"
        : "text-negative";

  return (
    <Link
      href={`/stocks/${row.ticker}`}
      className="flex shrink-0 items-baseline gap-2.5 px-5 py-3 transition-colors hover:bg-surface-hover"
    >
      <span className="font-mono text-xs font-semibold tracking-wide">{row.ticker}</span>
      <span className="font-mono text-xs text-text-secondary tabular-nums">
        {fmtPrice(row.close)}
      </span>
      <span className={`font-mono text-2xs tabular-nums ${tone}`}>{fmtPct(row.changePct)}</span>
    </Link>
  );
}

/**
 * The preferred majors first, then whatever else the universe holds, so the
 * strip is wide enough to fill a large screen with distinct symbols rather
 * than repeating the same eight.
 */
async function pickTickers(): Promise<string[]> {
  let universe: string[] = [];
  try {
    universe = (await listSymbols()).map((s) => s.ticker);
  } catch {
    // Fall back to the curated list; it's a strip of prices, not a feature.
  }

  const available = new Set(universe);
  const leading = universe.length ? PREFERRED.filter((t) => available.has(t)) : PREFERRED;
  const rest = universe.filter((t) => !leading.includes(t));
  return [...leading, ...rest].slice(0, MAX_TICKERS);
}

export async function MarketTicker() {
  const tickers = await pickTickers();
  const rows = await Promise.all(tickers.map((t) => loadRow(t)));

  // Sorted so the strongest movers lead the strip; "—" rows settle at the end.
  const sorted = [...rows].sort((a, b) => {
    if (a.changePct === null && b.changePct === null) return 0;
    if (a.changePct === null) return 1;
    if (b.changePct === null) return -1;
    return b.changePct - a.changePct;
  });

  return (
    <div className="marquee border-y border-border-muted bg-surface-secondary/30">
      <div className="marquee-track" style={{ ["--marquee-duration" as string]: "48s" }}>
        <div className="flex min-w-[100vw] shrink-0 items-center justify-around">
          {sorted.map((row) => (
            <TickerItem key={row.ticker} row={row} />
          ))}
        </div>
        <div className="flex min-w-[100vw] shrink-0 items-center justify-around" aria-hidden>
          {sorted.map((row) => (
            <TickerItem key={`${row.ticker}-dup`} row={row} />
          ))}
        </div>
      </div>
    </div>
  );
}
