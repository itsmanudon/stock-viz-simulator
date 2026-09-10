import type { JournalDaySummary, JournalMonth, JournalStats } from "@/lib/api/journal";

/**
 * Pure helpers behind the Trading Journal: month parsing, grid construction,
 * and P&L tint normalization.
 *
 * Nothing here fetches or renders. Keeping the arithmetic out of the
 * components is what makes the interesting cases — a month that starts on a
 * Saturday, a single outlier day, a scratch trade — testable directly.
 *
 * Accounting semantics live in `docs/TRADING_JOURNAL.md`; this file only
 * presents what the API already decided.
 */

/** `YYYY-MM`, the Journal's month URL parameter. */
export type MonthKey = string;

export type CalendarDay = {
  /** `YYYY-MM-DD`. */
  date: string;
  dayOfMonth: number;
  /** False for the leading/trailing days that pad the grid to whole weeks. */
  inMonth: boolean;
  isWeekend: boolean;
  isToday: boolean;
  summary: JournalDaySummary | null;
};

export type CalendarWeek = {
  /** `YYYY-MM-DD` of the week's Monday — the week inspector's key. */
  key: string;
  days: CalendarDay[];
  /** Null when the month's data has no row for this week (should not happen). */
  summary: JournalMonth["weeks"][number] | null;
};

const MONTH_PATTERN = /^(\d{4})-(\d{2})$/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
export const JOURNAL_TIMEZONE = "America/New_York";
export const MIN_JOURNAL_YEAR = 1970;
export const MAX_JOURNAL_YEAR = 2200;

/**
 * Parse `YYYY-MM`, falling back to `fallback` when absent or malformed.
 *
 * Dates in the Journal are plain calendar labels (New York trading sessions
 * resolved server-side), never instants — so they are parsed and formatted as
 * strings and never round-tripped through a `Date` in the viewer's timezone,
 * which would shift them.
 */
export function parseMonthKey(raw: string | undefined, fallback: MonthKey): MonthKey {
  if (!raw) return fallback;
  const match = MONTH_PATTERN.exec(raw);
  if (!match) return fallback;
  const month = Number(match[2]);
  const year = Number(match[1]);
  if (year < MIN_JOURNAL_YEAR || year > MAX_JOURNAL_YEAR) return fallback;
  if (month < 1 || month > 12) return fallback;
  return raw;
}

export function parseDateKey(raw: string | undefined): string | null {
  if (!raw) return null;
  const match = DATE_PATTERN.exec(raw);
  if (!match) return null;
  const [, year, month, day] = match;
  if (Number(year) < MIN_JOURNAL_YEAR || Number(year) > MAX_JOURNAL_YEAR) return null;
  if (Number(month) < 1 || Number(month) > 12) return null;
  if (Number(day) < 1 || Number(day) > daysInMonth(Number(year), Number(month))) return null;
  return raw;
}

export function monthKeyOf(year: number, month: number): MonthKey {
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function splitMonthKey(key: MonthKey): { year: number; month: number } {
  const match = MONTH_PATTERN.exec(key);
  if (!match) return { year: new Date().getFullYear(), month: new Date().getMonth() + 1 };
  return { year: Number(match[1]), month: Number(match[2]) };
}

export function shiftMonth(key: MonthKey, delta: number): MonthKey {
  const { year, month } = splitMonthKey(key);
  // Month index arithmetic, so December + 1 rolls the year without a Date.
  const index = Math.max(
    MIN_JOURNAL_YEAR * 12,
    Math.min(MAX_JOURNAL_YEAR * 12 + 11, year * 12 + (month - 1) + delta),
  );
  return monthKeyOf(Math.floor(index / 12), (index % 12) + 1);
}

/** Current month in the same timezone used by the ledger calendar. */
export function currentMonthKey(now: Date = new Date()): MonthKey {
  return todayKey(now).slice(0, 7);
}

/** New York calendar date; independent of the server or viewer's timezone. */
export function todayKey(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: JOURNAL_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function dateKey(year: number, month: number, day: number): string {
  return `${monthKeyOf(year, month)}-${String(day).padStart(2, "0")}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Monday-first weekday index (0 = Monday) for a plain calendar date. */
function weekdayIndex(year: number, month: number, day: number): number {
  // UTC on purpose: this is a calendar label, not an instant, so the viewer's
  // offset must not be able to move it to the previous day.
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

function addDays(year: number, month: number, day: number, delta: number): string {
  const at = new Date(Date.UTC(year, month - 1, day + delta));
  return dateKey(at.getUTCFullYear(), at.getUTCMonth() + 1, at.getUTCDate());
}

/**
 * Build the Monday-first grid for `month`, padded to whole weeks.
 *
 * Padding days belong to the neighbouring months and are marked `inMonth:
 * false`; they are rendered as inert spacers so the grid keeps its shape
 * without implying the Journal has data for them.
 *
 * Weekends stay in the grid rather than being hidden: a market order fills at
 * the latest close on any calendar day, so a Saturday fill is real data.
 */
export function buildCalendar(
  monthKey: MonthKey,
  data: JournalMonth | null,
  today: string = todayKey(),
): CalendarWeek[] {
  const { year, month } = splitMonthKey(monthKey);
  const total = daysInMonth(year, month);
  const summaries = new Map((data?.days ?? []).map((day) => [day.date, day]));
  const weekSummaries = new Map((data?.weeks ?? []).map((week) => [week.start, week]));

  const leading = weekdayIndex(year, month, 1);
  const weeks: CalendarWeek[] = [];
  let cursor = 1 - leading;

  while (cursor <= total) {
    const days: CalendarDay[] = [];
    for (let offset = 0; offset < 7; offset++) {
      const dayOfMonth = cursor + offset;
      const inMonth = dayOfMonth >= 1 && dayOfMonth <= total;
      const date = inMonth
        ? dateKey(year, month, dayOfMonth)
        : addDays(year, month, 1, dayOfMonth - 1);
      days.push({
        date,
        dayOfMonth: inMonth ? dayOfMonth : Number(date.slice(8)),
        inMonth,
        isWeekend: offset >= 5,
        isToday: date === today,
        summary: inMonth ? (summaries.get(date) ?? null) : null,
      });
    }
    // The API clips each week to the month, so the key is the first in-month
    // day of the row — which is the Monday except in the first week.
    const firstInMonth = days.find((day) => day.inMonth);
    const key = firstInMonth ? firstInMonth.date : days[0].date;
    weeks.push({ key, days, summary: weekSummaries.get(key) ?? null });
    cursor += 7;
  }

  return weeks;
}

export type TintLevel = 0 | 1 | 2 | 3;

export type Tint = {
  sign: "positive" | "negative" | "flat";
  level: TintLevel;
};

/**
 * The size of a *typical* trading day this month — the tint scale's anchor.
 *
 * The median of the month's non-zero absolute P&L. Median rather than mean or
 * max because it cannot be moved by one outsized day, which is exactly the
 * failure the tint has to survive: a single +$50k session must not flatten
 * every other day to the lightest tint. Month-local rather than account-wide,
 * so a quiet month still shows its own internal contrast.
 *
 * Returns 0 for a month with no realized movement, which `tintFor` reads as
 * "no scale to compare against".
 */
export function tintScale(values: number[]): number {
  const magnitudes = values
    .map((value) => Math.abs(value))
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  if (magnitudes.length === 0) return 0;

  const middle = Math.floor(magnitudes.length / 2);
  return magnitudes.length % 2 === 0
    ? (magnitudes[middle - 1] + magnitudes[middle]) / 2
    : magnitudes[middle];
}

/** Ratios to the month's median that separate a light, medium, and strong tint. */
export const TINT_MEDIUM_RATIO = 0.6;
export const TINT_STRONG_RATIO = 1.4;

/**
 * Bucket one day's P&L into a sign and one of three tint strengths.
 *
 * `ratio = |pnl| / median`, cut at 0.6 and 1.4 — in words: a day well under a
 * typical day this month gets the lightest tint, a day well over it the
 * strongest, everything in between the middle one. Deterministic, a pure
 * function of the month, and robust because the anchor is a median.
 *
 * (An earlier version scaled `log1p(|pnl|) / log1p(scale)`. It was wrong: a
 * ratio of logs sits near 1 for almost any two large numbers, so all but the
 * very smallest days collapsed onto the strongest tint. The bug is recorded
 * here because the transform looks reasonable until you plot it.)
 *
 * A day with exactly zero realized P&L is `flat`, not `positive` — scratch is
 * its own outcome, and it carries no tint at all.
 */
export function tintFor(pnl: number, scale: number): Tint {
  if (!Number.isFinite(pnl) || pnl === 0) return { sign: "flat", level: 0 };
  const sign = pnl > 0 ? "positive" : "negative";
  if (scale <= 0) return { sign, level: 1 };

  const ratio = Math.abs(pnl) / scale;
  if (ratio < TINT_MEDIUM_RATIO) return { sign, level: 1 };
  if (ratio < TINT_STRONG_RATIO) return { sign, level: 2 };
  return { sign, level: 3 };
}

/** Percentage of decided trades that made money, or null when none were. */
export function winRatePercent(stats: JournalStats): number | null {
  if (stats.win_rate === null || stats.win_rate === undefined) return null;
  return stats.win_rate * 100;
}

/** Compact P&L for the tightest cells: `+$5.3k`, `-$412`. */
export function formatCompactPnl(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) {
    const scaled = magnitude / 1000;
    return `${sign}$${scaled.toFixed(scaled >= 100 ? 0 : 1)}k`;
  }
  return `${sign}$${magnitude.toFixed(0)}`;
}

const MONTH_LABELS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function formatMonthLabel(key: MonthKey): string {
  const { year, month } = splitMonthKey(key);
  return `${MONTH_LABELS[month - 1]} ${year}`;
}

/** "August 19, 2026" from a plain `YYYY-MM-DD`, without timezone drift. */
export function formatDateLabel(date: string, { withYear = true, short = false } = {}): string {
  const match = DATE_PATTERN.exec(date);
  if (!match) return date;
  const [, year, month, day] = match;
  const name = MONTH_LABELS[Number(month) - 1];
  const base = `${short ? name.slice(0, 3) : name} ${Number(day)}`;
  return withYear ? `${base}, ${year}` : base;
}

/**
 * "Aug 3 – Aug 9, 2026", or the full date when the range is one day.
 *
 * Abbreviated inside a range because the inspector header is narrow and the
 * month name would otherwise appear twice at full length.
 */
export function formatRangeLabel(start: string, end: string): string {
  if (start === end) return formatDateLabel(start);
  const from = formatDateLabel(start, { withYear: false, short: true });
  const to = formatDateLabel(end, { short: true });
  return `${from} – ${to}`;
}

/**
 * Screen-reader sentence for a calendar cell.
 *
 * Gain and loss are stated in words, so the tint is never the only channel
 * carrying the outcome.
 */
export function describeDay(date: string, stats: JournalStats | null): string {
  const label = formatDateLabel(date, { withYear: false });
  if (!stats || stats.trade_count === 0) return `${label}, no closed trades`;

  const value = Number(stats.realized_pnl);
  const magnitude = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const outcome =
    value > 0
      ? `profit ${magnitude} dollars`
      : value < 0
        ? `loss ${magnitude} dollars`
        : "no net gain or loss";
  const trades = `${stats.trade_count} ${stats.trade_count === 1 ? "trade" : "trades"}`;
  return `${label}, ${outcome}, ${trades}`;
}
