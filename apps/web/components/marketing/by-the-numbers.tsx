/**
 * "By the numbers" band.
 *
 * Every figure is counted from a live public endpoint at render time. There is
 * deliberately no logo wall, no testimonial, and no "trusted by N traders" —
 * this is a personal paper-trading simulator, and invented social proof is the
 * fastest way to make an otherwise honest page read as fake. What it can
 * legitimately claim is the size and shape of the data behind it, so that is
 * what it claims, with a footnote saying where the numbers came from.
 *
 * A stat that can't be counted is omitted rather than shown as zero, and if
 * fewer than two survive the whole band disappears.
 */

import { Reveal } from "@/components/marketing/reveal";
import { ApiError, getBars, getMarketsSummary, getRecommendations } from "@/lib/api";

// Matches the tour's backtest ticker so the copy ("the window every backtest
// reads") stays literally true, and picks one with deep *and* fresh stored
// history.
const HISTORY_TICKER = "HDFCBANK.NS";

/**
 * The bars endpoint hard-caps `limit` at 5000 (`MAX_BARS` in
 * `routers/bars.py`), so a response of exactly this length means the stored
 * history is *at least* this deep, not exactly this deep — the count is a
 * floor and gets a "+" rather than being passed off as exact.
 */
const HISTORY_LIMIT = 5000;

type Stat = {
  value: string;
  label: string;
};

async function safe<T>(run: () => Promise<T>): Promise<T | null> {
  try {
    return await run();
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

function count(n: number): string {
  return n.toLocaleString("en-US");
}

export async function ByTheNumbers() {
  const [markets, bars, recs] = await Promise.all([
    safe(() => getMarketsSummary()),
    safe(() => getBars(HISTORY_TICKER, { limit: HISTORY_LIMIT })),
    safe(() => getRecommendations({ limit: 1, revalidateSeconds: 3600 })),
  ]);

  const stats: Stat[] = [];

  if (markets && markets.rows.length > 0) {
    stats.push({
      value: count(markets.rows.length),
      label:
        "symbols in the tracked universe — each with daily OHLCV, indicators, news, and a sentiment series.",
    });
  }

  if (bars && bars.length > 0) {
    const saturated = bars.length >= HISTORY_LIMIT;
    stats.push({
      value: `${count(bars.length)}${saturated ? "+" : ""}`,
      label: `sessions of stored daily history on ${HISTORY_TICKER} — the window every backtest and signal actually reads.`,
    });
  }

  // Read the rule set's size off a real recommendation rather than hardcoding
  // seven, so the copy can't drift if a vote is ever added or removed.
  const voteCount = recs?.[0]?.votes.length ?? 0;
  if (voteCount > 0) {
    stats.push({
      value: count(voteCount),
      label:
        "rule votes scored for every symbol, each one shown with its reasoning — including the votes that fail.",
    });
  }

  if (markets && markets.sectors.length > 0) {
    stats.push({
      value: count(markets.sectors.length),
      label: "sectors to screen, compare, and allocate across.",
    });
  }

  if (stats.length < 2) return null;

  return (
    <section aria-labelledby="numbers-heading" className="panel-inset rounded-none border-x-0">
      {/* Phase 1's blueprint grid, masked so it fades before it reaches the
          text. Decorative only. */}
      <div aria-hidden className="grid-backdrop pointer-events-none absolute inset-0 opacity-40" />

      <div className="relative mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <Reveal>
          <p className="font-mono text-2xs tracking-[0.16em] text-brand uppercase">
            What&rsquo;s actually in here
          </p>
          <h2
            id="numbers-heading"
            className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight text-balance sm:text-4xl"
          >
            No claims we can&rsquo;t count
          </h2>
        </Reveal>

        <dl className="mt-10">
          {stats.map((stat, index) => (
            <Reveal key={stat.label} delay={index * 70}>
              <div className="grid items-baseline gap-x-8 gap-y-2 border-t border-border-muted py-6 sm:grid-cols-[minmax(0,14rem)_1fr] sm:py-7">
                <dt className="font-mono text-4xl leading-none font-semibold tabular-nums sm:text-5xl">
                  {stat.value}
                </dt>
                <dd className="text-sm leading-6 text-text-secondary sm:text-base">{stat.label}</dd>
              </div>
            </Reveal>
          ))}
        </dl>

        <p className="mt-8 font-mono text-2xs text-text-tertiary">
          Counted from the public API when this page was rendered. End-of-day bars only — nothing
          here is exchange real-time data.
        </p>
      </div>
    </section>
  );
}
