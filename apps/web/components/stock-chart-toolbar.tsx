"use client";

import { Check, ChevronDown, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DropdownMenu } from "radix-ui";

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
  STOCK_INDICATORS,
  STOCK_INTERVALS,
  STOCK_TIMEFRAMES,
  type StockIndicator,
  type StockInterval,
  type StockTimeframe,
  buildStockChartHref,
} from "@/lib/stock-workspace";

export function StockChartToolbar({
  ticker,
  timeframe,
  indicators,
  interval = "1d",
  view = DEFAULT_CHART_VIEW,
  hasRaw = false,
}: {
  ticker: string;
  timeframe: StockTimeframe;
  indicators: StockIndicator[];
  interval?: StockInterval;
  /** A3.1: chart type, price scale and adjusted/raw prices. */
  view?: ChartView;
  /** Whether raw exchange prices are stored for this symbol. */
  hasRaw?: boolean;
}) {
  const router = useRouter();

  function toggleIndicator(indicator: StockIndicator) {
    const next = new Set(indicators);
    if (next.has(indicator)) next.delete(indicator);
    else next.add(indicator);
    router.push(buildStockChartHref(ticker, timeframe, Array.from(next), interval, view));
  }

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
          {STOCK_TIMEFRAMES.map((value) => (
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
              href={buildStockChartHref(ticker, timeframe, indicators, option.value, view)}
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

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-2 rounded-md border border-border-muted px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground data-[state=open]:bg-surface-hover data-[state=open]:text-foreground"
            aria-label={`Indicators, ${indicators.length} selected`}
          >
            <SlidersHorizontal className="size-3.5" aria-hidden />
            Indicators
            {indicators.length ? (
              <span className="font-mono text-3xs text-brand">{indicators.length}</span>
            ) : null}
            <ChevronDown className="size-3" aria-hidden />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={6}
            className="z-50 min-w-48 rounded-md border border-border-muted bg-popover p-1"
          >
            <DropdownMenu.Label className="px-2 py-1.5 text-3xs font-semibold uppercase tracking-[0.12em] text-text-tertiary">
              Technical indicators
            </DropdownMenu.Label>
            {STOCK_INDICATORS.map((indicator, index) => [
              index === 0 || STOCK_INDICATORS[index - 1].section !== indicator.section ? (
                <DropdownMenu.Label
                  key={`label-${indicator.section}`}
                  className="px-2 pt-2 pb-1 text-3xs text-text-tertiary"
                >
                  {indicator.section === "price" ? "On the price chart" : "Below the chart"}
                </DropdownMenu.Label>
              ) : null,
              <DropdownMenu.CheckboxItem
                key={indicator.value}
                checked={indicators.includes(indicator.value)}
                onSelect={(event) => {
                  event.preventDefault();
                  toggleIndicator(indicator.value);
                }}
                className="relative flex h-8 cursor-default select-none items-center rounded-sm py-1 pl-8 pr-2 text-xs text-muted-foreground outline-none data-[highlighted]:bg-surface-hover data-[highlighted]:text-foreground"
              >
                <span className="absolute left-2 inline-flex size-4 items-center justify-center text-brand">
                  <DropdownMenu.ItemIndicator>
                    <Check className="size-3.5" aria-hidden />
                  </DropdownMenu.ItemIndicator>
                </span>
                {indicator.label}
              </DropdownMenu.CheckboxItem>,
            ])}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
