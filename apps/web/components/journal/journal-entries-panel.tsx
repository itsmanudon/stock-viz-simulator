"use client";

/**
 * Journal entries on the Portfolio Journal tab (A5.5, M10.3): one row per
 * round trip (flat to flat, partial exits included) in the selected book, or
 * every book and replay session in All books. Each row: entry date, symbol,
 * R, net P&L, MAE / MFE, the plan badge and the source; it opens the entry
 * page. Figures come from the API (computed on read); this only filters.
 */

import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { edgeHref } from "@/lib/journal-edge";
import {
  BADGE_CLASS,
  type JournalEntrySummary,
  SOURCE_LABEL,
  TONE_CLASS,
  entryHref,
  entryPlanBadge,
  excursionPct,
  money,
  rText,
  tone,
} from "@/lib/journal-entries";
import { formatCloseDate } from "@/lib/stock-workspace";

type StatusFilter = "all" | "open" | "closed";
const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

export function JournalEntriesPanel({
  entries,
  total,
  note,
  book,
}: {
  entries: JournalEntrySummary[] | null;
  total: number;
  note: string | null;
  book: number | "all" | null;
}) {
  const id = useId();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [source, setSource] = useState<"all" | JournalEntrySummary["source"]>("all");
  const sources = useMemo(
    () => Array.from(new Set((entries ?? []).map((e) => e.source))),
    [entries],
  );
  const shown = useMemo(
    () =>
      (entries ?? []).filter(
        (e) =>
          (status === "all" || e.status === status) && (source === "all" || e.source === source),
      ),
    [entries, status, source],
  );

  return (
    <section aria-labelledby={`${id}-title`} className="space-y-4" data-testid="journal-entries">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={`${id}-title`} className="text-base font-semibold tracking-tight">
            Journal Entries
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary">
            {note ??
              "One row per round trip, flat to flat. The P&L calendar below counts each closing fill on its own day."}
          </p>
          <Link
            href={edgeHref(book)}
            className="mt-2 inline-flex text-sm font-medium text-foreground underline underline-offset-2 hover:text-brand"
            data-testid="edge-link"
          >
            Is My Edge Real? Statistics over your closed trades
          </Link>
        </div>
        {entries?.length ? (
          <div className="flex flex-wrap gap-3">
            <Chips
              label="Filter entries by status"
              options={STATUS_FILTERS}
              value={status}
              onChange={setStatus}
            />
            {sources.length > 1 ? (
              <Chips
                label="Filter entries by source"
                options={[
                  { value: "all" as const, label: "Any Source" },
                  ...sources.map((s) => ({ value: s, label: SOURCE_LABEL[s] })),
                ]}
                value={source}
                onChange={setSource}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      {entries === null ? (
        <p className="text-sm text-muted-foreground">Journal entries are unavailable right now.</p>
      ) : entries.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-muted px-4 py-5 text-sm text-text-secondary">
          No round trips yet. A buy opens an entry here; it closes when the position is back to
          zero.
        </p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">No entries match these filters.</p>
      ) : (
        <>
          <ul className="divide-y divide-border-muted rounded-md border border-border-muted">
            {shown.map((entry) => (
              <EntryRow key={entry.id} entry={entry} book={book} />
            ))}
          </ul>
          {total > (entries?.length ?? 0) ? (
            <p className="text-xs text-text-tertiary">
              Showing the newest {entries.length} of {total} entries.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

function Chips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="flex flex-wrap gap-1.5" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`h-7 rounded-full border px-3 text-xs ${
            value === o.value
              ? "border-brand/50 bg-brand/10 text-foreground"
              : "border-border-muted text-muted-foreground hover:bg-surface-hover"
          }`}
        >
          {o.label}
        </button>
      ))}
    </fieldset>
  );
}

function EntryRow({ entry, book }: { entry: JournalEntrySummary; book: number | "all" | null }) {
  const badge = entryPlanBadge(entry);
  const pnlTone = TONE_CLASS[tone(entry.net_pnl)];
  const rTone = TONE_CLASS[tone(entry.r_multiple)];
  const dates = entry.exit_date
    ? `${formatCloseDate(entry.entry_date)} → ${formatCloseDate(entry.exit_date)}`
    : `${formatCloseDate(entry.entry_date)} → Open`;
  return (
    <li data-testid="journal-entry-row" data-status={entry.status} data-source={entry.source}>
      <Link
        href={entryHref(entry.id, book)}
        className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 px-4 py-3 hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:outline-none md:grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))_auto] md:items-center"
      >
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="ticker font-semibold">{entry.ticker ?? "—"}</span>
            <span className="rounded-full border border-border-muted px-2 py-0.5 text-2xs tracking-[0.02em] text-text-secondary">
              {SOURCE_LABEL[entry.source]}
            </span>
            <span
              data-testid="entry-plan-badge"
              className={`rounded-full border px-2 py-0.5 text-2xs tracking-[0.02em] ${BADGE_CLASS[badge.tone]}`}
            >
              {badge.label}
            </span>
          </p>
          <p className="mt-1 text-xs text-text-secondary">{dates}</p>
        </div>
        <Figure label="R" className={`text-right md:text-left ${rTone}`} testId="entry-r">
          {rText(entry.r_multiple)}
        </Figure>
        <Figure label="Net P&L" className={pnlTone} testId="entry-pnl">
          {money(entry.net_pnl, entry.currency)}
          {entry.status === "open" ? (
            <span className="ml-1 text-2xs text-text-tertiary">Open</span>
          ) : null}
        </Figure>
        <Figure label="MAE" className={TONE_CLASS.loss} testId="entry-mae">
          {excursionPct(entry.excursions.mae)}
        </Figure>
        <Figure label="MFE" className={TONE_CLASS.gain} testId="entry-mfe">
          {excursionPct(entry.excursions.mfe)}
        </Figure>
        <Figure label="Size" className="text-text-secondary">
          {Number(entry.quantity).toLocaleString("en-US")}
        </Figure>
      </Link>
    </li>
  );
}

function Figure({
  label,
  className = "",
  testId,
  children,
}: {
  label: string;
  className?: string;
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="text-2xs tracking-[0.02em] text-text-tertiary">{label}</p>
      <p data-testid={testId} className={`font-mono text-sm tabular-nums ${className}`}>
        {children}
      </p>
    </div>
  );
}
