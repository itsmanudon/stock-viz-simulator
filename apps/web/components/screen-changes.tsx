/**
 * A screen notification's entries and exits (A2.3): the symbols that met the
 * saved screen's rule tonight and not last session, and the reverse. Read
 * from the notification's `data`; anything else renders nothing.
 */

import Link from "next/link";

function tickers(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((t): t is string => typeof t === "string") : [];
}

export function screenChanges(data: Record<string, unknown> | null | undefined): {
  entries: string[];
  exits: string[];
} | null {
  if (!data) return null;
  const entries = tickers(data.entries);
  const exits = tickers(data.exits);
  return entries.length || exits.length ? { entries, exits } : null;
}

function Row({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-baseline gap-1.5">
      <dt className="text-2xs font-medium text-text-tertiary uppercase">{label}</dt>
      <dd className="flex flex-wrap gap-1">
        {items.map((t) => (
          <Link
            key={t}
            href={`/stocks/${encodeURIComponent(t)}`}
            className={`rounded-sm border border-border-muted px-1.5 font-mono text-2xs hover:underline ${tone}`}
          >
            {t}
          </Link>
        ))}
      </dd>
    </div>
  );
}

export function ScreenChanges({ data }: { data: Record<string, unknown> | null | undefined }) {
  const changes = screenChanges(data);
  if (!changes) return null;
  return (
    <dl className="mt-1.5 space-y-1" data-testid="screen-changes">
      <Row
        label={`Entered (${changes.entries.length})`}
        items={changes.entries}
        tone="text-positive"
      />
      <Row label={`Left (${changes.exits.length})`} items={changes.exits} tone="text-negative" />
    </dl>
  );
}
