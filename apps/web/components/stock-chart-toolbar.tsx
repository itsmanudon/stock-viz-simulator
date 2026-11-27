"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { IndicatorMenu } from "@/components/indicator-menu";
import { VolumeProfileToggle } from "@/components/volume-profile-toggle";
import type { IndicatorCatalogItem } from "@/lib/api/types";
import {
  EVENT_LABELS,
  EVENT_TYPES,
  resolveEventTypes,
  toggleEventsParam,
} from "@/lib/chart-events";
import {
  CHART_SCALES,
  CHART_TYPES,
  type ChartType,
  type ChartView,
  DEFAULT_CHART_VIEW,
  PRICE_ADJUSTMENTS,
  RAW_UNAVAILABLE_NOTE,
} from "@/lib/chart-view";
import {
  INTRADAY_INTERVALS,
  type IntradayInterval,
  STOCK_INTERVALS,
  STOCK_TIMEFRAMES,
  type StockIndicator,
  type StockInterval,
  type StockTimeframe,
  buildStockChartHref,
  intradayLookbacks,
  intradayWords,
  isIntradayInterval,
  parseIntradayLookback,
} from "@/lib/stock-workspace";

export function StockChartToolbar({
  ticker,
  timeframe,
  indicators,
  interval = "1d",
  view = DEFAULT_CHART_VIEW,
  hasRaw = false,
  catalog = null,
  signedIn = false,
  intradayIntervals = [],
  volumeProfile,
}: {
  ticker: string;
  timeframe: StockTimeframe;
  indicators: StockIndicator[];
  interval?: StockInterval;
  /** A3.1: chart type, price scale and adjusted/raw prices. */
  view?: ChartView;
  /** Whether raw exchange prices are stored for this symbol. */
  hasRaw?: boolean;
  /** A3.4: the studies' parameters and evidence badges (null when the call failed). */
  catalog?: IndicatorCatalogItem[] | null;
  /** A3.5: fills are offered (and on by default) only when signed in. */
  signedIn?: boolean;
  /** A6.2: the intraday intervals the symbol has (none: the buttons are hidden). */
  intradayIntervals?: readonly string[];
  /** A6.7: the volume profile switch (absent: not shown); `offered` false for an index. */
  volumeProfile?: { offered: boolean };
}) {
  const intraday = isIntradayInterval(interval);
  // The lookbacks follow the interval: daily ranges, or the intraday ones.
  const lookbacks: readonly StockTimeframe[] = isIntradayInterval(interval)
    ? intradayLookbacks(interval)
    : STOCK_TIMEFRAMES;
  const offered = INTRADAY_INTERVALS.filter((i) => intradayIntervals.includes(i.value));
  /** A link to another interval keeps the lookback when that interval offers it. */
  const intervalHref = (next: StockInterval) => {
    const tf: StockTimeframe = isIntradayInterval(next)
      ? parseIntradayLookback(timeframe, next as IntradayInterval)
      : intraday
        ? "1Y"
        : timeframe;
    return buildStockChartHref(ticker, tf, indicators, next, view);
  };
  const router = useRouter();

  const hrefWith = (patch: Partial<ChartView>) =>
    buildStockChartHref(ticker, timeframe, indicators, interval, { ...view, ...patch });
  const segment = (active: boolean) =>
    `inline-flex h-7 min-w-8 items-center justify-center rounded-sm px-2 text-xs font-medium transition-colors ${
      active
        ? "bg-brand/12 text-brand"
        : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
    }`;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-muted px-3 py-2.5 sm:px-4">
      <div className="flex flex-wrap items-center gap-2">
        <nav aria-label="Chart timeframe" className="flex items-center gap-0.5">
          {lookbacks.map((value) => (
            <Link
              key={value}
              href={buildStockChartHref(ticker, value, indicators, interval, view)}
              aria-current={timeframe === value ? "page" : undefined}
              className={`inline-flex h-8 min-w-9 items-center justify-center rounded-md px-2 font-mono text-xs font-medium transition-colors ${
                timeframe === value
                  ? "bg-brand/12 text-brand"
                  : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
              }`}
            >
              {value}
            </Link>
          ))}
        </nav>

        {/* A1.4a: bar interval, separate from the lookback range. */}
        <nav
          aria-label="Bar interval"
          className="flex items-center gap-0.5 rounded-md border border-border-muted p-0.5"
        >
          {STOCK_INTERVALS.map((option) => (
            <Link
              key={option.value}
              href={intervalHref(option.value)}
              aria-current={interval === option.value ? "page" : undefined}
              aria-label={`${option.label} bars`}
              className={`inline-flex h-7 min-w-8 items-center justify-center rounded-sm px-2 text-xs font-medium transition-colors ${
                interval === option.value
                  ? "bg-brand/12 text-brand"
                  : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
              }`}
            >
              <span className="sm:hidden" aria-hidden>
                {option.short}
              </span>
              <span className="hidden sm:inline" aria-hidden>
                {option.label}
              </span>
            </Link>
          ))}
        </nav>

        {/* A6.2: intraday intervals, only when the symbol has intraday bars. */}
        {offered.length ? (
          <nav
            aria-label="Intraday interval"
            className="flex items-center gap-0.5 rounded-md border border-border-muted p-0.5"
            data-testid="intraday-intervals"
          >
            {offered.map((option) => (
              <Link
                key={option.value}
                href={intervalHref(option.value)}
                aria-current={interval === option.value ? "page" : undefined}
                aria-label={`${intradayWords(option.value)} bars`}
                data-interval={option.value}
                className={`inline-flex h-7 min-w-8 items-center justify-center rounded-sm px-1.5 font-mono text-xs font-medium transition-colors ${
                  interval === option.value
                    ? "bg-brand/12 text-brand"
                    : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                }`}
              >
                <span aria-hidden>{option.short}</span>
              </Link>
            ))}
          </nav>
        ) : null}
      </div>

      {/* A3.1: chart type, price scale and adjusted/raw prices. */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="sr-only sm:not-sr-only">Type</span>
          <select
            aria-label="Chart type"
            value={view.type}
            onChange={(event) => router.push(hrefWith({ type: event.target.value as ChartType }))}
            className="h-8 rounded-md border border-border-muted bg-card px-2 text-xs font-medium text-foreground hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
          >
            {CHART_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        <nav
          aria-label="Price scale"
          className="flex items-center gap-0.5 rounded-md border border-border-muted p-0.5"
        >
          {CHART_SCALES.map((option) => (
            <Link
              key={option.value}
              href={hrefWith({ scale: option.value })}
              aria-current={view.scale === option.value ? "page" : undefined}
              aria-label={`${option.label} scale`}
              className={segment(view.scale === option.value)}
            >
              <span aria-hidden>{option.short}</span>
            </Link>
          ))}
        </nav>

        <nav
          aria-label="Price adjustment"
          className="flex items-center gap-0.5 rounded-md border border-border-muted p-0.5"
        >
          {PRICE_ADJUSTMENTS.map((option) =>
            option.value === "raw" && !hasRaw ? (
              // Focusable but inert, so the keyboard reaches the reason.
              <button
                key={option.value}
                type="button"
                aria-disabled="true"
                aria-label={`Raw prices: ${RAW_UNAVAILABLE_NOTE}`}
                title={RAW_UNAVAILABLE_NOTE}
                className="inline-flex h-7 min-w-8 cursor-not-allowed items-center justify-center rounded-sm px-2 text-xs font-medium text-text-tertiary opacity-60"
                data-testid="raw-unavailable"
              >
                {option.label}
              </button>
            ) : (
              <Link
                key={option.value}
                href={hrefWith({ adjustment: option.value })}
                aria-current={view.adjustment === option.value ? "page" : undefined}
                aria-label={`${option.label} prices`}
                className={segment(view.adjustment === option.value)}
              >
                {option.label}
              </Link>
            ),
          )}
        </nav>
      </div>

      <IndicatorMenu
        indicators={indicators}
        catalog={catalog}
        onChange={(next) =>
          router.push(buildStockChartHref(ticker, timeframe, next, interval, view))
        }
      />

      {volumeProfile ? <VolumeProfileToggle offered={volumeProfile.offered} /> : null}

      {/* A3.5: one toggle per event type; the choice is URL state (?events=). */}
      <EventToggles
        hrefFor={(events) =>
          buildStockChartHref(ticker, timeframe, indicators, interval, { ...view, events })
        }
        param={view.events}
        signedIn={signedIn}
      />
    </div>
  );
}

export function EventToggles({
  hrefFor,
  param,
  signedIn,
}: {
  hrefFor: (events: string | undefined) => string;
  param: string | undefined;
  signedIn: boolean;
}) {
  const shown = new Set(resolveEventTypes(param, signedIn));
  const types = EVENT_TYPES.filter((t) => t !== "fill" || signedIn);
  return (
    <nav
      aria-label="Chart events"
      className="flex w-full flex-wrap items-center gap-1"
      data-testid="event-toggles"
    >
      <span className="mr-1 text-2xs text-text-tertiary">Events</span>
      {types.map((type) => {
        const on = shown.has(type);
        return (
          <Link
            key={type}
            href={hrefFor(toggleEventsParam(param, type, signedIn))}
            scroll={false}
            role="switch"
            aria-checked={on}
            aria-label={`${on ? "Hide" : "Show"} ${EVENT_LABELS[type].toLowerCase()} on the chart`}
            data-event-type={type}
            className={`inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-2xs font-medium transition-colors ${
              on
                ? "border-border bg-surface-hover text-foreground"
                : "border-border-muted text-text-tertiary hover:text-foreground"
            }`}
          >
            <span
              aria-hidden
              className="size-1.5 rounded-full"
              style={{
                background: on ? `var(${EVENT_TOKEN[type]})` : "transparent",
                outline: "1px solid currentColor",
              }}
            />
            {EVENT_LABELS[type]}
          </Link>
        );
      })}
    </nav>
  );
}

/** The CSS token each marker type is drawn in (the chart reads the same tokens). */
const EVENT_TOKEN = {
  news: "--list-violet",
  earnings: "--list-amber",
  dividend: "--list-lime",
  split: "--list-blue",
  fill: "--foreground",
} as const;
