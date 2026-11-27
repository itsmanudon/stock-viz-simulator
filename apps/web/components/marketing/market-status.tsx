/**
 * Data-freshness chip in the workspace top bar. The public header's chip went
 * on 27 Nov 2026: on the landing page every price already carries its close
 * date ("Moving at the latest close" cards, the footer's close line).
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
import { formatCloseDate } from "@/lib/stock-workspace";

// Liquid names first, so the badge reports the freshest bar the ingest holds.
const CANDIDATES = ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "AAPL", "MSFT", "NVDA"];

/** A Fri close read on Monday is still current; beyond this the ingest is late. */
const FRESH_DAYS = 4;

const MS_PER_DAY = 86_400_000;

/**
 * Calendar date (`YYYY-MM-DD`) of the most recent stored end-of-day bar.
 *
 * Read straight from the stored timestamp. Parsing it with `new Date()` read
 * the zone-less value as local time, so on a server east of UTC the badge
 * showed the day before the close (UI audit T2). Also used by the landing
 * page to date its movers.
 */
export async function latestStoredCloseDate(): Promise<string | null> {
  for (const ticker of CANDIDATES) {
    try {
      const bars = await getBars(ticker, { limit: 1 });
      const day = bars[0]?.ts.slice(0, 10);
      if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      // Try the next candidate.
    }
  }
  return null;
}

/**
 * The product top bar's data-date label: "EOD data · latest close Nov 7, 2026".
 *
 * The same honest claim as `MarketStatus`, worded for the workspace and with
 * the year, as every product date carries one. It names the newest stored
 * bar only; symbols end on different days, so pages still date each row.
 * Hidden below `sm`, where the search box needs the width. Renders nothing
 * when no bar can be read.
 */
/** True while the stored day is recent enough to count as current. */
export function isFreshClose(day: string): boolean {
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  return (Date.now() - Date.UTC(year, month - 1, dayOfMonth)) / MS_PER_DAY <= FRESH_DAYS;
}

export async function DataDateChip() {
  const day = await latestStoredCloseDate();
  const label = formatCloseDate(day);
  if (!day || !label) return null;

  const fresh = isFreshClose(day);

  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border-muted px-2.5 py-1 font-mono text-2xs whitespace-nowrap text-text-secondary sm:inline-flex"
      title={`Most recent stored end-of-day bar: ${day}. Prices are not live quotes.`}
    >
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${fresh ? "bg-positive" : "bg-warning"}`}
      />
      EOD data · latest close {label}
    </span>
  );
}
