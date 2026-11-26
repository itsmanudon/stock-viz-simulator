"use client";

/**
 * A4.1: a strategy's trades on A3's price chart. Entry and exit markers
 * (`PriceChart` `markers`) on the symbol's daily bars over the run's range;
 * a basket picks one symbol at a time. Marker colours come from the chart
 * palette, never hard-coded.
 */

import { useEffect, useMemo, useState } from "react";

import { strategyBarsAction } from "@/app/(product)/backtest/strategy-actions";
import { PriceChart } from "@/components/price-chart";
import { Label } from "@/components/ui/label";
import type { ApiInterval, Bar } from "@/lib/api/types";
import { useChartPalette } from "@/lib/chart-theme";
import { type StrategyTrade, tradeMarkers } from "@/lib/rule-strategy";

export function StrategyTradesChart({
  tickers,
  trades,
  from,
  to,
  loadBars = strategyBarsAction,
  interval = "1d",
  timeZone = "UTC",
  feed = null,
}: {
  tickers: string[];
  trades: StrategyTrade[];
  from: string;
  to: string;
  loadBars?: (ticker: string, from: string, to: string, interval?: ApiInterval) => Promise<Bar[]>;
  /** A6.4: an intraday run's bars (its timeframe), in the venue's zone. */
  interval?: "1d" | "1m" | "5m" | "15m" | "30m" | "60m";
  timeZone?: string;
  feed?: string | null;
}) {
  const withTrades = useMemo(() => {
    const traded = new Set(trades.map((t) => t.ticker));
    return [...tickers].sort((a, b) => Number(traded.has(b)) - Number(traded.has(a)));
  }, [tickers, trades]);
  const [ticker, setTicker] = useState(withTrades[0] ?? "");
  const [bars, setBars] = useState<Bar[] | null>(null);
  const palette = useChartPalette();

  useEffect(() => {
    if (!ticker) return;
    let live = true;
    setBars(null);
    loadBars(ticker, from, to, interval).then((rows) => {
      if (live) setBars(rows);
    });
    return () => {
      live = false;
    };
  }, [ticker, from, to, loadBars, interval]);

  const markers = useMemo(
    () => tradeMarkers(trades, ticker, { entry: palette.positive, exit: palette.negative }),
    [trades, ticker, palette],
  );
  const count = trades.filter((t) => t.ticker === ticker).length;

  return (
    <div className="space-y-2" data-testid="strategy-chart">
      {tickers.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor="strategy-chart-symbol" className="text-xs">
            Symbol
          </Label>
          <select
            id="strategy-chart-symbol"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="h-9 rounded-sm border border-input bg-transparent px-2 text-sm"
          >
            {withTrades.map((t) => (
              <option key={t} value={t}>
                {t} ({trades.filter((x) => x.ticker === t).length} trades)
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {bars === null ? (
        <p className="py-10 text-center text-sm text-text-secondary">Loading {ticker}…</p>
      ) : bars.length === 0 ? (
        <p className="py-10 text-center text-sm text-text-secondary">
          No bars stored for {ticker}.
        </p>
      ) : (
        <PriceChart
          bars={bars}
          markers={markers}
          showVolume={false}
          interval={interval}
          timeZone={timeZone}
          sourceFeed={feed}
        />
      )}
      <p className="text-xs text-text-tertiary" data-testid="strategy-chart-caption">
        {ticker}: {count} trade{count === 1 ? "" : "s"}. B and S mark long and short entries; exits
        say why: X exit rule, SL fixed stop, ATR stop, TS trailing stop, T time stop, C session
        close, "gap" when the bar opened through the stop.
      </p>
    </div>
  );
}
