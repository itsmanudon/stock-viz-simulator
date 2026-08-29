/**
 * Data-freshness chip in the public header.
 *
 * Says exactly what the product actually has: the date of the most recent
 * stored end-of-day bar. It deliberately does NOT claim a live or open market —
 * the engine settles against stored daily closes, and a green "LIVE" dot here
 * would be the first thing on the page to misrepresent that.
 *
 * The dot reads freshness, not direction: positive while the latest bar is
 * within a few days (a normal weekend gap), warning once the ingest has
 * clearly fallen behind. Renders nothing at all if no bars can be read, rather
 * than showing a placeholder date.
 */

import { ApiError, getBars } from "@/lib/api";

const CANDIDATES = ["AAPL", "MSFT", "NVDA"];

/** A Fri close read on Monday is still current; beyond this the ingest is late. */
const FRESH_DAYS = 4;

const MS_PER_DAY = 86_400_000;

async function latestBarDate(): Promise<Date | null> {
  for (const ticker of CANDIDATES) {
    try {
      const bars = await getBars(ticker, { limit: 1 });
      if (bars.length > 0) {
        const parsed = new Date(bars[0].ts);
        if (!Number.isNaN(parsed.getTime())) return parsed;
      }
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      // Try the next candidate.
    }
  }
  return null;
}

export async function MarketStatus() {
  const date = await latestBarDate();
  if (!date) return null;

  // Fixed to UTC so the server render is deterministic and the label can't
  // disagree with itself between regions.
  const label = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  })
    .format(date)
    .toUpperCase();

  const ageDays = (Date.now() - date.getTime()) / MS_PER_DAY;
  const fresh = ageDays <= FRESH_DAYS;

  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border-muted px-2.5 py-1 font-mono text-2xs text-text-tertiary lg:inline-flex"
      title={`Most recent stored end-of-day bar: ${date.toISOString().slice(0, 10)}`}
    >
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${fresh ? "bg-positive" : "bg-warning"}`}
      />
      EOD · {label}
    </span>
  );
}
