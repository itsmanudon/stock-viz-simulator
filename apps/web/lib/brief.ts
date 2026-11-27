/** A9.12 (M11.6): pure helpers for the brief and the weekly review (client-safe). */

export function moveText(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

export function shiftWeek(end: string, days: number): string {
  const d = new Date(`${end}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function weekHref(end: string, book?: string): string {
  const q = new URLSearchParams({ week_end: end });
  if (book) q.set("book", book);
  return `/portfolio/journal/week?${q.toString()}`;
}
