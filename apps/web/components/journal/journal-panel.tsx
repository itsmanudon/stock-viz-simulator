"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type InspectorTarget, JournalInspector } from "@/components/journal/journal-inspector";
import { JournalSummary } from "@/components/journal/journal-summary";
import { PnlCalendar } from "@/components/journal/pnl-calendar";
import { Button } from "@/components/ui/button";
import type { JournalDay, JournalMonth, JournalWeek } from "@/lib/api/journal";
import {
  type MonthKey,
  parseDateKey,
  parseMonthKey,
  splitMonthKey,
} from "@/lib/journal-view-model";

/**
 * The Trading Journal tab: month state, lazy detail fetching, and URL sync.
 *
 * State lives in the URL (`?tab=journal&month=…&date=…&week=…`) so a view is
 * shareable and Back/Forward behave. Updates go through the native History
 * API, which App Router feeds back into `useSearchParams()` — that keeps month
 * navigation instant instead of re-running the whole portfolio page's data
 * load on every arrow press.
 *
 * The first month is server-rendered and handed in as `initialMonth`, so the
 * calendar paints with data rather than a skeleton.
 */
export function JournalPanel({
  initialMonthKey,
  initialMonth,
  initialError,
}: {
  initialMonthKey: MonthKey;
  initialMonth: JournalMonth | null;
  initialError: boolean;
}) {
  const searchParams = useSearchParams();
  const monthKey = parseMonthKey(searchParams.get("month") ?? undefined, initialMonthKey);
  const parsedDate = parseDateKey(searchParams.get("date") ?? undefined);
  const parsedWeek = parseDateKey(searchParams.get("week") ?? undefined);
  const dateParam = parsedDate?.startsWith(`${monthKey}-`) ? parsedDate : null;
  const weekParam = parsedWeek?.startsWith(`${monthKey}-`) ? parsedWeek : null;

  const [months, setMonths] = useState<Record<string, JournalMonth>>(() =>
    initialMonth ? { [initialMonthKey]: initialMonth } : {},
  );
  const [monthLoading, setMonthLoading] = useState(false);
  const [monthError, setMonthError] = useState<string | null>(
    initialError ? "The journal service didn't respond." : null,
  );

  const [day, setDay] = useState<JournalDay | null>(null);
  const [dayLoading, setDayLoading] = useState(false);
  const [dayError, setDayError] = useState<string | null>(null);
  const [moreLoading, setMoreLoading] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [weekDetail, setWeekDetail] = useState<JournalWeek | null>(null);
  const [weekError, setWeekError] = useState<string | null>(null);
  const [weekRetry, setWeekRetry] = useState(0);

  const monthRequest = useRef<AbortController | null>(null);
  const dayRequest = useRef<AbortController | null>(null);
  // Avoid duplicating the initial SSR request; revalidate on later visits.
  const requestedMonths = useRef(
    new Set<string>(initialMonth || initialError ? [initialMonthKey] : []),
  );

  const month = months[monthKey] ?? null;

  /**
   * Push Journal state into the URL without a server round trip.
   *
   * Built from the params React last rendered, not from `window.location`, so
   * the next URL is always a delta on the state actually on screen.
   */
  const setParams = useCallback(
    (changes: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [name, value] of Object.entries(changes)) {
        if (value === null) params.delete(name);
        else params.set(name, value);
      }
      window.history.pushState(null, "", `${window.location.pathname}?${params.toString()}`);
    },
    [searchParams],
  );

  const loadMonth = useCallback(async (key: MonthKey) => {
    monthRequest.current?.abort();
    const controller = new AbortController();
    monthRequest.current = controller;

    const { year, month: monthNumber } = splitMonthKey(key);
    requestedMonths.current.add(key);
    setMonthLoading(true);
    setMonthError(null);
    try {
      const res = await fetch(`/api/journal/months/${year}/${monthNumber}`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const body = (await res.json()) as JournalMonth;
      if (controller.signal.aborted) return;
      // Keep only a small working set; revisiting a month revalidates it.
      setMonths((current) =>
        Object.fromEntries([
          ...Object.entries(current)
            .filter(([entry]) => entry !== key)
            .slice(-5),
          [key, body],
        ]),
      );
    } catch (err) {
      if (controller.signal.aborted) return;
      // Let a retry re-request this month.
      requestedMonths.current.delete(key);
      setMonthError(err instanceof Error ? err.message : "Request failed");
    } finally {
      if (!controller.signal.aborted) setMonthLoading(false);
    }
  }, []);

  // Cached months paint immediately while subsequent visits revalidate them.
  useEffect(() => {
    setMonthLoading(false);
    if (!requestedMonths.current.has(monthKey)) void loadMonth(monthKey);
    return () => {
      monthRequest.current?.abort();
      requestedMonths.current.delete(monthKey);
    };
  }, [monthKey, loadMonth]);

  /**
   * Load one day's trades, cancelling whatever was in flight.
   *
   * Aborting first is what stops a slow Aug 19 response from landing on top of
   * a fast Aug 21 one when the user clicks through a week quickly. The panel
   * is cleared at the same time, so a new title never sits over old numbers.
   */
  const loadDay = useCallback(async (date: string) => {
    dayRequest.current?.abort();
    const controller = new AbortController();
    dayRequest.current = controller;

    setDayLoading(true);
    setDayError(null);
    setDay(null);
    setMoreLoading(false);
    setMoreError(null);
    try {
      const res = await fetch(`/api/journal/days/${date}`, { signal: controller.signal });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const body = (await res.json()) as JournalDay;
      if (controller.signal.aborted) return;
      setDay(body);
    } catch (err) {
      if (controller.signal.aborted) return;
      setDayError(err instanceof Error ? err.message : "Request failed");
    } finally {
      if (!controller.signal.aborted) setDayLoading(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (!day || day.date !== dateParam || !day.has_more || moreLoading) return;
    dayRequest.current?.abort();
    const controller = new AbortController();
    dayRequest.current = controller;
    setMoreLoading(true);
    setMoreError(null);
    try {
      const res = await fetch(`/api/journal/days/${day.date}?offset=${day.executions.length}`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error("Couldn't load more trades. Try again.");
      const body = (await res.json()) as JournalDay;
      if (controller.signal.aborted) return;
      setDay((current) =>
        current?.date === body.date
          ? { ...body, executions: [...current.executions, ...body.executions] }
          : current,
      );
    } catch (err) {
      if (!controller.signal.aborted)
        setMoreError(err instanceof Error ? err.message : "Request failed");
    } finally {
      if (!controller.signal.aborted) setMoreLoading(false);
    }
  }, [day, dateParam, moreLoading]);

  // Retry changes the resource identity without changing the selected week.
  const weekRequestKey = `${weekParam ?? ""}:${weekRetry}`;
  useEffect(() => {
    const [start] = weekRequestKey.split(":");
    setWeekDetail(null);
    setWeekError(null);
    if (!start || dateParam) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const res = await fetch(`/api/journal/weeks/${start}`, { signal: controller.signal });
        if (!res.ok) throw new Error("Couldn't load trade highlights.");
        const body = (await res.json()) as JournalWeek;
        if (!controller.signal.aborted) setWeekDetail(body);
      } catch (err) {
        if (!controller.signal.aborted)
          setWeekError(err instanceof Error ? err.message : "Request failed");
      }
    })();
    return () => controller.abort();
  }, [weekRequestKey, dateParam]);

  useEffect(() => {
    if (!dateParam) {
      dayRequest.current?.abort();
      setDay(null);
      setDayError(null);
      setDayLoading(false);
      return;
    }
    void loadDay(dateParam);
    return () => dayRequest.current?.abort();
  }, [dateParam, loadDay]);

  useEffect(() => {
    const refresh = () => {
      void loadMonth(monthKey);
      if (dateParam) void loadDay(dateParam);
      setWeekRetry((value) => value + 1);
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [monthKey, dateParam, loadMonth, loadDay]);

  const target: InspectorTarget | null = dateParam
    ? { mode: "day", date: dateParam }
    : weekParam && month?.weeks.some((week) => week.start === weekParam)
      ? { mode: "week", start: weekParam }
      : null;

  const selectedWeek = useMemo(
    () => month?.weeks.find((week) => week.start === weekParam) ?? null,
    [month, weekParam],
  );

  const weekDays = useMemo(() => {
    if (!selectedWeek || !month) return [];
    return month.days.filter(
      (entry) => entry.date >= selectedWeek.start && entry.date <= selectedWeek.end,
    );
  }, [month, selectedWeek]);

  const openDay = useCallback((date: string) => setParams({ date, week: null }), [setParams]);
  const openWeek = useCallback(
    (start: string) => setParams({ week: start, date: null }),
    [setParams],
  );
  const closeInspector = useCallback(
    (open: boolean) => {
      if (!open) setParams({ date: null, week: null });
    },
    [setParams],
  );

  const changeMonth = useCallback(
    (next: MonthKey) => setParams({ month: next, date: null, week: null }),
    [setParams],
  );

  const isEmptyMonth =
    month !== null && month.summary.trade_count === 0 && !month.unavailable_count;

  return (
    <section
      aria-labelledby="journal-heading"
      data-inspecting={target !== null}
      className="journal-workspace min-w-0 space-y-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="journal-heading" className="text-lg font-semibold tracking-tight">
            Trading journal
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Realized profit and loss by execution date · New York time (ET).
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            One trade is one closing fill or option settlement. Win rate excludes breakeven trades.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void loadMonth(monthKey);
            if (dateParam) void loadDay(dateParam);
            setWeekRetry((value) => value + 1);
          }}
        >
          Refresh
        </Button>
      </div>

      {monthError && !month ? (
        <div className="rounded-md border border-border-muted bg-card p-5">
          <p className="text-sm font-medium">Couldn't load the journal.</p>
          <p className="mt-1 text-xs text-muted-foreground">{monthError}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void loadMonth(monthKey)}
          >
            Try again
          </Button>
        </div>
      ) : null}
      <>
        <JournalSummary monthKey={monthKey} data={month} loading={monthLoading} />

        {monthError && month ? (
          // The previous month is still on screen and still correct; say the
          // refresh failed instead of blanking it.
          <p className="text-xs text-negative">
            Couldn't refresh this month ({monthError}).{" "}
            <button type="button" className="underline" onClick={() => void loadMonth(monthKey)}>
              Retry
            </button>
          </p>
        ) : null}

        <PnlCalendar
          monthKey={monthKey}
          data={month}
          loading={monthLoading}
          selectedDate={dateParam}
          selectedWeek={weekParam}
          onMonthChange={changeMonth}
          onSelectDay={openDay}
          onSelectWeek={openWeek}
        />

        {month?.unavailable_count ? (
          <p
            aria-live="polite"
            className="rounded-md border border-border-muted bg-card p-4 text-sm text-muted-foreground"
          >
            Incomplete history: {month.unavailable_count} historical closing records lack reliable
            USD accounting. Totals include only recorded realizations.
          </p>
        ) : null}

        {isEmptyMonth ? (
          <div className="rounded-md border border-border-muted bg-card p-5">
            <p className="text-sm font-medium">No closed trades this month.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Your realized trading activity will appear here after positions are closed.
            </p>
          </div>
        ) : null}
      </>

      <JournalInspector
        target={target}
        day={day?.date === dateParam ? day : null}
        week={selectedWeek}
        dayDates={weekDays}
        loading={Boolean(dateParam) && (dayLoading || (!dayError && day?.date !== dateParam))}
        error={dateParam ? dayError : null}
        onOpenChange={closeInspector}
        onSelectDay={openDay}
        weekDetail={weekDetail?.start === weekParam ? weekDetail : null}
        weekError={weekError}
        onRetryWeek={() => setWeekRetry((value) => value + 1)}
        moreLoading={moreLoading}
        moreError={moreError}
        onLoadMore={() => void loadMore()}
        onRetry={() => {
          if (dateParam) void loadDay(dateParam);
        }}
      />
    </section>
  );
}
