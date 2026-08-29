"use client";

import { Check, ChevronDown, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DropdownMenu } from "radix-ui";

import {
  STOCK_INDICATORS,
  STOCK_TIMEFRAMES,
  type StockIndicator,
  type StockTimeframe,
  buildStockChartHref,
} from "@/lib/stock-workspace";

export function StockChartToolbar({
  ticker,
  timeframe,
  indicators,
}: {
  ticker: string;
  timeframe: StockTimeframe;
  indicators: StockIndicator[];
}) {
  const router = useRouter();

  function toggleIndicator(indicator: StockIndicator) {
    const next = new Set(indicators);
    if (next.has(indicator)) next.delete(indicator);
    else next.add(indicator);
    router.push(buildStockChartHref(ticker, timeframe, Array.from(next)));
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-muted px-3 py-2.5 sm:px-4">
      <nav aria-label="Chart timeframe" className="flex items-center gap-0.5">
        {STOCK_TIMEFRAMES.map((value) => (
          <Link
            key={value}
            href={buildStockChartHref(ticker, value, indicators)}
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
            {STOCK_INDICATORS.map((indicator) => (
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
              </DropdownMenu.CheckboxItem>
            ))}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}
