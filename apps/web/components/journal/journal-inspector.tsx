"use client";

import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useRef, useState } from "react";

import { JournalExecutionRow } from "@/components/journal/journal-execution-row";
import { Button } from "@/components/ui/button";
import type { JournalDay, JournalStats, JournalWeek, JournalWeekSummary } from "@/lib/api/journal";
import { formatDateLabel, formatRangeLabel, winRatePercent } from "@/lib/journal-view-model";
import { formatCurrency } from "@/lib/portfolio-view-model";
import { cn } from "@/lib/utils";

export type InspectorTarget = { mode: "day"; date: string } | { mode: "week"; start: string };

/** Stable keys for the loading placeholder's fixed-length rows. */
const SKELETON_STATS = ["pnl", "trades", "winners", "losers"];
const SKELETON_ROWS = ["a", "b", "c"];

/**
 * The Journal's detail surface.
 *
 * One Dialog with two shapes: a right-side slide-over from `lg` up, so the
 * calendar stays visible and the left app sidebar is never covered, and a
 * bottom sheet below that. Selecting another day updates the open panel in
 * place instead of closing and reopening it.
 */
export function JournalInspector({
  target,
  day,
  week,
  dayDates,
  loading,
  error,
  onOpenChange,
  onSelectDay,
  onRetry,
  weekDetail,
  weekError,
  onRetryWeek,
  moreLoading,
  moreError,
  onLoadMore,
}: {
  target: InspectorTarget | null;
  day: JournalDay | null;
  week: JournalWeekSummary | null;
  /** Day summaries inside the selected week, for the week view's breakdown. */
  dayDates: { date: string; stats: JournalStats }[];
  loading: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onSelectDay: (date: string) => void;
  onRetry: () => void;
  weekDetail: JournalWeek | null;
  weekError: string | null;
  onRetryWeek: () => void;
  moreLoading: boolean;
  moreError: string | null;
  onLoadMore: () => void;
}) {
  const [mobile, setMobile] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  const open = target !== null;
  useEffect(() => {
    if (!window.matchMedia) return;
    const query = window.matchMedia("(max-width: 1023px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const title =
    target === null
      ? ""
      : target.mode === "day"
        ? formatDateLabel(target.date)
        : week
          ? `Week of ${formatRangeLabel(week.start, week.end)}`
          : "Week";

  return (
    // `modal={false}` on purpose: a modal dialog blocks pointer events outside
    // itself, which would stop the whole point of this panel — clicking Aug 19,
    // then Aug 20, then Aug 21 and watching it update in place. Outside
    // interaction is also prevented from *dismissing* it, so a click on the
    // calendar selects a day instead of closing the inspector. Escape and the
    // close button remain the ways out, and on mobile the scrim closes it too.
    <Dialog.Root open={open} onOpenChange={onOpenChange} modal={mobile}>
      <Dialog.Portal>
        {/* The scrim is a mobile affordance only. On desktop the calendar has
            to stay legible and clickable behind the panel. */}
        <Dialog.Overlay
          onClick={() => onOpenChange(false)}
          className="journal-veil fixed inset-0 z-40 bg-black/50 lg:hidden"
        />
        <Dialog.Content
          aria-modal={mobile || undefined}
          aria-describedby={undefined}
          onInteractOutside={(event) => {
            if (!mobile) event.preventDefault();
          }}
          onOpenAutoFocus={(event) => {
            returnFocus.current = document.activeElement as HTMLElement;
            if (!mobile) event.preventDefault();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus.current?.focus();
          }}
          // `journal-inspector` carries the slide; see globals.css for why the
          // motion is hand-written keyframes rather than animate-in/out.
          className={cn(
            "journal-inspector fixed z-50 flex flex-col overflow-hidden bg-surface-elevated outline-none",
            // Below `lg`: a bottom sheet that never covers the whole screen.
            "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-lg border-t border-border-muted",
            // From `lg` up: a right-hand inspector. The calendar keeps its place.
            "lg:inset-y-0 lg:left-auto lg:right-0 lg:h-full lg:max-h-none lg:w-[22rem] xl:w-[26rem] lg:rounded-none lg:border-l lg:border-t-0",
          )}
        >
          <header className="flex items-start justify-between gap-3 border-b border-border-muted px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-base font-semibold tracking-tight">
                {title}
              </Dialog.Title>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Realized P&L · USD · New York execution dates
              </p>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close journal detail"
                className="inline-flex size-10 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:size-8"
              >
                <X className="size-5 sm:size-4" aria-hidden />
              </button>
            </Dialog.Close>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {(target?.mode === "week" ? weekDetail?.unavailable_count : day?.unavailable_count) ? (
              <p className="mb-4 rounded-md border border-border-muted p-3 text-xs text-muted-foreground">
                Incomplete history: some closing records lack reliable USD accounting. Only recorded
                realizations are shown.
              </p>
            ) : null}
            {error ? (
              // Scoped to the inspector: the calendar behind it stays intact.
              <div className="rounded-md border border-border-muted bg-card p-4">
                <p className="text-sm font-medium">Couldn't load this day.</p>
                <p className="mt-1 text-xs text-muted-foreground">{error}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
                  Try again
                </Button>
              </div>
            ) : target?.mode === "week" ? (
              <>
                <WeekBody week={weekDetail ?? week} days={dayDates} onSelectDay={onSelectDay} />
                {weekError ? (
                  <p className="mt-4 text-sm" aria-live="polite">
                    {weekError}{" "}
                    <button type="button" className="underline" onClick={onRetryWeek}>
                      Retry
                    </button>
                  </p>
                ) : weekDetail ? (
                  <div className="mt-5 space-y-4">
                    {(["best_trade", "worst_trade"] as const).map((key) =>
                      weekDetail[key] ? (
                        <section key={key}>
                          <h3 className="text-xs font-semibold text-muted-foreground">
                            {key === "best_trade" ? "Best trade" : "Worst trade"}
                          </h3>
                          <ul>
                            <JournalExecutionRow execution={weekDetail[key]} />
                          </ul>
                          <button
                            type="button"
                            className="text-xs underline"
                            onClick={() =>
                              onSelectDay(weekDetail[key]?.session_date ?? weekDetail.start)
                            }
                          >
                            Open day
                          </button>
                        </section>
                      ) : null,
                    )}
                  </div>
                ) : (
                  <p className="mt-4 text-xs text-muted-foreground" aria-live="polite">
                    Loading trade highlights…
                  </p>
                )}
              </>
            ) : loading ? (
              <DaySkeleton />
            ) : (
              <>
                <DayBody day={day} />
                {moreError ? (
                  <p aria-live="polite" className="mt-3 text-sm">
                    {moreError}
                  </p>
                ) : null}
                {day?.has_more ? (
                  <Button
                    className="mt-4"
                    variant="outline"
                    disabled={moreLoading}
                    onClick={onLoadMore}
                  >
                    {moreLoading ? "Loading trades…" : "Load more trades"}
                  </Button>
                ) : null}
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DayBody({ day }: { day: JournalDay | null }) {
  if (!day || day.stats.trade_count === 0) {
    return (
      <div className="py-6">
        <p className="text-sm font-medium">No recorded realized P&L on this day.</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Realized gains and losses appear here once a position is closed.
        </p>
      </div>
    );
  }

  return (
    <>
      <StatGrid stats={day.stats} currency={day.currency} />
      <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-text-tertiary">
        Trades
      </h3>
      <ul className="mt-1">
        {day.executions.map((execution) => (
          <JournalExecutionRow
            key={`${execution.kind}-${execution.reference_id}`}
            execution={execution}
          />
        ))}
      </ul>
    </>
  );
}

function WeekBody({
  week,
  days,
  onSelectDay,
}: {
  week: JournalWeekSummary | null;
  days: { date: string; stats: JournalStats }[];
  onSelectDay: (date: string) => void;
}) {
  if (!week || week.stats.trade_count === 0) {
    return (
      <div className="py-6">
        <p className="text-sm font-medium">No recorded realized P&L this week.</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick a week with activity, or open a day to see its trades.
        </p>
      </div>
    );
  }

  return (
    <>
      <StatGrid stats={week.stats} currency="USD" extended />
      <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-text-tertiary">
        Daily breakdown
      </h3>
      <ul className="mt-1">
        {days.map((entry) => {
          const pnl = Number(entry.stats.realized_pnl);
          return (
            <li key={entry.date} className="border-b border-border-muted last:border-b-0">
              <button
                type="button"
                onClick={() => onSelectDay(entry.date)}
                className="flex w-full items-baseline justify-between gap-3 py-2.5 text-left transition-colors hover:text-foreground"
              >
                <span className="text-sm">{formatDateLabel(entry.date, { withYear: false })}</span>
                <span className="flex items-baseline gap-3">
                  <span className="font-mono text-3xs text-text-tertiary">
                    {entry.stats.trade_count} {entry.stats.trade_count === 1 ? "trade" : "trades"}
                  </span>
                  <span
                    data-financial
                    className={cn(
                      "font-mono text-sm font-semibold",
                      pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : "text-text-secondary",
                    )}
                  >
                    {pnl > 0 ? "+" : pnl < 0 ? "−" : ""}
                    {formatCurrency(Math.abs(pnl), "USD")}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function StatGrid({
  stats,
  currency,
  extended = false,
}: {
  stats: JournalStats;
  currency: string;
  extended?: boolean;
}) {
  const pnl = Number(stats.realized_pnl);
  const winRate = winRatePercent(stats);

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
      <Row
        label="Realized P&L"
        value={`${pnl > 0 ? "+" : pnl < 0 ? "−" : ""}${formatCurrency(Math.abs(pnl), currency)}`}
        tone={pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral"}
      />
      <Row label="Trades" value={String(stats.trade_count)} />
      <Row label="Winners" value={String(stats.winning_trades)} />
      <Row label="Losers" value={String(stats.losing_trades)} />
      <Row label="Win rate" value={winRate === null ? "—" : `${winRate.toFixed(0)}%`} />
      {extended ? (
        <Row
          label="Profit factor"
          value={stats.profit_factor === null ? "—" : stats.profit_factor.toFixed(2)}
        />
      ) : null}
    </dl>
  );
}

function Row({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-xs text-muted-foreground">{label}</dt>
      <dd
        data-financial
        className={cn(
          "mt-0.5 truncate font-mono text-sm font-semibold",
          tone === "positive" && "text-positive",
          tone === "negative" && "text-negative",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * Fixed-shape placeholder while a day loads.
 *
 * Switching days keeps the panel open, so the old day's numbers must not stay
 * on screen under a new title — this replaces them until the new ones land.
 */
function DaySkeleton() {
  return (
    <div aria-busy className="animate-pulse">
      <span className="sr-only">Loading trades</span>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {SKELETON_STATS.map((id) => (
          <div key={id}>
            <div className="h-3 w-16 rounded-sm bg-surface-secondary" />
            <div className="mt-1.5 h-4 w-20 rounded-sm bg-surface-secondary" />
          </div>
        ))}
      </div>
      <div className="mt-6 space-y-4">
        {SKELETON_ROWS.map((id) => (
          <div key={id} className="h-16 rounded-md bg-surface-secondary" />
        ))}
      </div>
    </div>
  );
}
