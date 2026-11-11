/**
 * Reading API timestamps (audit RS-2).
 *
 * The API stores UTC and sends it with no zone ("2025-04-04T00:00:00"),
 * because its datetimes are naive. `new Date()` reads a zone-less date-time as
 * the browser's local time, so east of UTC every such value moved back by the
 * offset: a bar dated 4 Apr landed on 3 Apr on the charts, and a fill at
 * 20:00 UTC showed as 11:00 UTC in Tokyo. Parse API timestamps here, never
 * with `new Date(iso)`.
 *
 * For a bar's calendar date as text, use `formatCloseDate()`
 * (`lib/stock-workspace.ts`), which reads the date from the string itself.
 */

const ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?$/;

/** Milliseconds since the epoch, reading a zone-less value as UTC. NaN if unreadable. */
export function apiTimestampMs(iso: string): number {
  if (ZONE.test(iso)) return Date.parse(iso);
  const match = DATE_TIME.exec(iso);
  if (!match) return Number.NaN;
  const [, year, month, day, hour = "0", minute = "0", second = "0", fraction = "0"] = match;
  return Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
    Number(fraction.padEnd(3, "0").slice(0, 3)),
  );
}

/** The instant an API timestamp names, as a Date. Invalid Date if unreadable. */
export function parseApiTimestamp(iso: string): Date {
  return new Date(apiTimestampMs(iso));
}

/** Whole seconds since the epoch, for chart time axes (which display UTC). */
export function barTimeToUtcSeconds(iso: string): number {
  return Math.floor(apiTimestampMs(iso) / 1000);
}
