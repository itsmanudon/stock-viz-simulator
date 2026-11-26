/**
 * /portfolio/journal/[id] — A5.5 (M10.3): one journal entry, a round trip
 * from flat to flat. Its figures (net P&L, R, MAE, MFE, holding), the A3
 * chart with the fills, the plan's lines and MAE / MFE marked, plan
 * adherence, news at entry and exit (headlines only), and the review form.
 * Every figure comes from `/v1/journal/entries/{id}`, computed on read.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { type Figure, FigureStrip } from "@/components/figure-strip";
import { JournalEntryChart } from "@/components/journal/journal-entry-chart";
import { JournalReviewForm } from "@/components/journal/journal-review-form";
import { MetaChip, PageHeader } from "@/components/page-header";
import type { Bar } from "@/lib/api";
import { formatUtcDateTime } from "@/lib/api-time";
import { getBars } from "@/lib/api/bars";
import { getJournalEntry } from "@/lib/api/journal-entries";
import { AuthedApiError } from "@/lib/api/server";
import {
  BADGE_CLASS,
  type JournalEntry,
  type JournalExcursion,
  type JournalNewsWindow,
  SOURCE_LABEL,
  TONE_CLASS,
  entryPlanBadge,
  excursionPct,
  money,
  rText,
  tone,
} from "@/lib/journal-entries";
import { formatCloseDate } from "@/lib/stock-workspace";

export const metadata: Metadata = { title: "Journal entry" };

const DAY_MS = 86_400_000;

function shiftDate(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d) + days * DAY_MS).toISOString().slice(0, 10);
}

/** Bars around the entry. A replay entry never reads past its last fill or mark (the clock). */
async function entryBars(entry: JournalEntry): Promise<Bar[]> {
  if (!entry.ticker) return [];
  const end = entry.exit_date ?? entry.as_of_date ?? entry.entry_date;
  const to = entry.source === "replay" ? end : shiftDate(end, 10);
  return getBars(entry.ticker, { from: shiftDate(entry.entry_date, -21), to }).catch(() => []);
}

export default async function JournalEntryPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ book?: string }>;
}) {
  const { id: raw } = await params;
  const { book } = await searchParams;
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0) notFound();
  let entry: JournalEntry;
  try {
    entry = await getJournalEntry(id);
  } catch (error) {
    if (error instanceof AuthedApiError && error.status === 404) notFound();
    throw error;
  }
  const bars = await entryBars(entry);
  const cur = entry.currency;
  const badge = entryPlanBadge(entry);
  const back = `/portfolio?tab=journal${book ? `&book=${encodeURIComponent(book)}` : ""}`;
  const exc = entry.excursions;

  const figures: Figure[] = [
    {
      label: "Net P&L",
      value: (
        <span data-testid="entry-net-pnl" className={TONE_CLASS[tone(entry.net_pnl)]}>
          {money(entry.net_pnl, cur)}
        </span>
      ),
      note: entry.fees_estimated
        ? `After ${money(entry.fees, cur)} estimated charges`
        : `After ${money(entry.fees, cur)} fees`,
    },
    {
      label: "R Multiple",
      value: (
        <span data-testid="entry-r-multiple" className={TONE_CLASS[tone(entry.r_multiple)]}>
          {rText(entry.r_multiple)}
        </span>
      ),
      note: entry.r_reason ?? `Risk ${money(entry.initial_risk, cur)} at the stop`,
    },
    {
      label: "MAE",
      value: (
        <span data-testid="entry-mae-figure" className={TONE_CLASS.loss}>
          {excursionPct(exc.mae)}
        </span>
      ),
      note: excursionNote(exc.mae, cur),
    },
    {
      label: "MFE",
      value: (
        <span data-testid="entry-mfe-figure" className={TONE_CLASS.gain}>
          {excursionPct(exc.mfe)}
        </span>
      ),
      note: excursionNote(exc.mfe, cur),
    },
    {
      label: "Average Entry",
      value: money(entry.avg_entry, cur),
      note: `${Number(entry.quantity).toLocaleString("en-US")} shares at most`,
    },
    {
      label: entry.status === "open" ? "Marked At" : "Average Exit",
      value:
        entry.status === "open"
          ? entry.mark_close
            ? money(entry.mark_close, cur)
            : "—"
          : money(entry.avg_exit, cur),
      note:
        entry.status === "open"
          ? entry.as_of_date
            ? `Open: last close ${formatCloseDate(entry.as_of_date)}`
            : "Open: no close yet"
          : `${entry.fills_count} fills`,
    },
    {
      label: "Holding",
      value: `${entry.holding_days} days`,
      note: `${entry.holding_sessions} sessions`,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-6 sm:px-6 lg:py-7">
      <div>
        <Link
          href={back}
          className="text-sm text-text-secondary underline-offset-2 hover:underline"
        >
          ← Journal
        </Link>
      </div>
      <PageHeader
        eyebrow="Portfolio · Journal"
        title={`${entry.ticker ?? "Unknown symbol"} Round Trip`}
        description={
          entry.exit_date
            ? `${formatCloseDate(entry.entry_date)} to ${formatCloseDate(entry.exit_date)}, dated by the ${entry.venue} session.`
            : `Opened ${formatCloseDate(entry.entry_date)} and still held, dated by the ${entry.venue} session.`
        }
        meta={
          <span className="flex flex-wrap items-center gap-2">
            <MetaChip>{SOURCE_LABEL[entry.source]}</MetaChip>
            <MetaChip tone={entry.status === "open" ? "warning" : "neutral"}>
              {entry.status === "open" ? "Open" : "Closed"}
            </MetaChip>
            <span
              data-testid="entry-plan-badge"
              className={`rounded-full border px-2.5 py-0.5 text-xs tracking-[0.02em] ${BADGE_CLASS[badge.tone]}`}
            >
              {badge.label}
            </span>
            <MetaChip>{cur}</MetaChip>
          </span>
        }
      />

      <FigureStrip figures={figures} label="Round trip figures" />
      <p className="-mt-5 text-xs text-text-tertiary" data-testid="entry-basis">
        {exc.reason ?? exc.note}
        {exc.mae?.r !== undefined && exc.mae?.r !== null
          ? ` MAE ${rText(exc.mae.r)}, MFE ${rText(exc.mfe?.r)} of the initial risk.`
          : ""}
      </p>

      <section aria-labelledby="entry-chart-title" className="space-y-3">
        <h2 id="entry-chart-title" className="text-base font-semibold tracking-tight">
          Chart
        </h2>
        <JournalEntryChart entry={entry} bars={bars} />
        <p className="text-xs text-text-tertiary">
          B and S mark the fills (the closing fill shows the entry&rsquo;s R); circles mark MAE and
          MFE; the plan&rsquo;s entry, stop and target are the labelled lines.
        </p>
      </section>

      <div className="grid gap-8 lg:grid-cols-2">
        <PlanSection entry={entry} />
        <FillsSection entry={entry} />
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <NewsSection
          title="News at Entry"
          window={entry.news_at_entry ?? null}
          testId="news-at-entry"
        />
        <NewsSection
          title="News at Exit"
          window={entry.news_at_exit ?? null}
          testId="news-at-exit"
          empty={entry.status === "open" ? "Still open: no exit yet." : undefined}
        />
      </div>

      <section aria-labelledby="entry-review-title" className="space-y-3">
        <h2 id="entry-review-title" className="text-base font-semibold tracking-tight">
          Review
        </h2>
        <JournalReviewForm entry={entry} />
      </section>
    </div>
  );
}

function excursionNote(e: JournalExcursion | null | undefined, cur: string): string {
  if (!e) return "Unknown";
  return `${money(e.amount, cur)} on ${formatCloseDate(e.date)}`;
}

function PlanSection({ entry }: { entry: JournalEntry }) {
  const plan = entry.plan;
  const cur = entry.currency;
  return (
    <section aria-labelledby="entry-plan-title" className="space-y-3" data-testid="entry-plan">
      <h2 id="entry-plan-title" className="text-base font-semibold tracking-tight">
        Plan
      </h2>
      {!plan ? (
        <p className="text-sm text-text-secondary">
          No plan was paired with this entry, so it has no R or adherence check.
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
            {[
              ["Entry", plan.planned_entry],
              ["Stop", plan.planned_stop],
              ["Target", plan.planned_target],
              ["Size", plan.planned_size],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-2xs tracking-[0.02em] text-text-tertiary">{label}</dt>
                <dd className="font-mono tabular-nums">
                  {value === null || value === undefined
                    ? "—"
                    : label === "Size"
                      ? Number(value).toLocaleString("en-US")
                      : money(value, cur)}
                </dd>
              </div>
            ))}
          </dl>
          <p className="text-sm text-text-secondary">
            {plan.label === "locked"
              ? `Locked at the first fill${plan.locked_at ? `, ${formatUtcDateTime(plan.locked_at)}` : ""}.`
              : "Written after entry: shown here, but left out of plan-adherence stats."}
            {plan.setup_label ? ` Setup: ${plan.setup_label}.` : ""}
          </p>
          {entry.adherence ? (
            <ul className="space-y-1.5" data-testid="entry-adherence">
              {entry.adherence.checks.map((check) => (
                <li key={check.key} className="text-sm">
                  <span
                    className={`mr-2 rounded-full border px-2 py-0.5 text-2xs tracking-[0.02em] ${
                      check.status === "passed"
                        ? "border-positive/40 text-gain"
                        : check.status === "failed"
                          ? "border-negative/40 text-loss"
                          : "border-border-muted text-text-tertiary"
                    }`}
                  >
                    {check.label}:{" "}
                    {check.status === "not_applicable"
                      ? "Not Tested"
                      : check.status === "passed"
                        ? "Passed"
                        : "Failed"}
                  </span>
                  <span className="text-text-secondary">{check.detail}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {entry.adherence_note ? (
            <p className="text-xs text-text-tertiary">{entry.adherence_note}</p>
          ) : null}
        </>
      )}
    </section>
  );
}

function FillsSection({ entry }: { entry: JournalEntry }) {
  const cur = entry.currency;
  return (
    <section aria-labelledby="entry-fills-title" className="space-y-3">
      <h2 id="entry-fills-title" className="text-base font-semibold tracking-tight">
        Fills
      </h2>
      <ul className="divide-y divide-border-muted rounded-md border border-border-muted">
        {entry.fills.map((f) => (
          <li
            key={`${f.trade_id ?? ""}-${f.replay_fill_id ?? ""}`}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2.5 text-sm"
          >
            <span>
              <span className="font-medium">{f.side === "buy" ? "Bought" : "Sold"}</span>{" "}
              <span className="font-mono tabular-nums">
                {Number(f.quantity).toLocaleString("en-US")} at {money(f.price, cur)}
              </span>
            </span>
            <span className="text-xs text-text-secondary">
              {formatCloseDate(f.venue_date)}
              {f.time_known ? "" : " (time not in the file)"}
              {Number(f.fees) > 0
                ? ` · ${money(f.fees, cur)} ${f.fees_estimated ? "estimated charges" : "fees"}`
                : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NewsSection({
  title,
  window: w,
  testId,
  empty,
}: {
  title: string;
  window: JournalNewsWindow | null;
  testId: string;
  empty?: string;
}) {
  return (
    <section aria-label={title} className="space-y-3" data-testid={testId}>
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      {!w ? (
        <p className="text-sm text-text-secondary">{empty ?? "No news window."}</p>
      ) : (
        <>
          <p className="text-xs text-text-tertiary">
            {formatCloseDate(w.from_date)} to {formatCloseDate(w.to_date)}.{" "}
            {w.coverage === "before_news_copy" || w.headlines.length === 0 ? w.note : ""}
          </p>
          {w.headlines.length ? (
            <ul className="space-y-2">
              {w.headlines.map((h) => (
                <li key={h.id} className="text-sm" data-testid="entry-headline">
                  {h.url ? (
                    <a
                      href={h.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="underline-offset-2 hover:underline"
                    >
                      {h.title}
                    </a>
                  ) : (
                    h.title
                  )}
                  <span className="block text-xs text-text-tertiary">
                    {h.source ?? "Unknown source"} · {formatCloseDate(h.date)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
