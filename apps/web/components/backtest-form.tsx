"use client";

/**
 * Interactive backtest form + results.
 *
 * The /v1/backtest endpoint is public, so this client component calls it
 * directly from the browser — no server action needed. Results render in
 * place: summary stat cards, an equity-curve chart, and a trade log.
 */

import { useState } from "react";

import { EquityCurve } from "@/components/equity-curve";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, type BacktestRequest, type BacktestResult, runBacktest } from "@/lib/api";

type SymbolOption = { ticker: string; name: string };
type StrategyType = "rsi_threshold" | "sma_crossover";

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

function fmtCurrency(raw: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtPct(fraction: number): string {
  const pct = fraction * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function parseApiDetail(err: ApiError): string {
  try {
    const parsed = JSON.parse(err.message.split(": ").slice(2).join(": ")) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    // fall through
  }
  return err.message;
}

export function BacktestForm({ symbols }: { symbols: SymbolOption[] }) {
  const [ticker, setTicker] = useState(symbols[0]?.ticker ?? "");
  const [from, setFrom] = useState(isoDaysAgo(365));
  const [to, setTo] = useState(isoDaysAgo(0));
  const [initialCash, setInitialCash] = useState("100000");
  const [strategyType, setStrategyType] = useState<StrategyType>("rsi_threshold");
  const [buyBelow, setBuyBelow] = useState("30");
  const [sellAbove, setSellAbove] = useState("70");
  const [shortWindow, setShortWindow] = useState("20");
  const [longWindow, setLongWindow] = useState("50");
  const [commissionBps, setCommissionBps] = useState("0");
  const [slippageBps, setSlippageBps] = useState("0");

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);

    const strategy: BacktestRequest["strategy"] =
      strategyType === "rsi_threshold"
        ? {
            type: "rsi_threshold",
            buy_below: Number(buyBelow),
            sell_above: Number(sellAbove),
          }
        : {
            type: "sma_crossover",
            short_window: Number(shortWindow),
            long_window: Number(longWindow),
          };

    try {
      const res = await runBacktest({
        ticker,
        from,
        to,
        initial_cash: initialCash,
        strategy,
        commission_bps: Number(commissionBps) || 0,
        slippage_bps: Number(slippageBps) || 0,
      });
      setResult(res);
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? parseApiDetail(err) : "Backtest failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardContent className="p-6">
          <form onSubmit={onSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="bt-ticker">Symbol</Label>
              <select
                id="bt-ticker"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                required
                className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {symbols.map((s) => (
                  <option key={s.ticker} value={s.ticker}>
                    {s.ticker} — {s.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="bt-from">From</Label>
                <Input
                  id="bt-from"
                  type="date"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bt-to">To</Label>
                <Input
                  id="bt-to"
                  type="date"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="bt-cash">Initial cash</Label>
              <Input
                id="bt-cash"
                type="number"
                min="1"
                step="1"
                value={initialCash}
                onChange={(e) => setInitialCash(e.target.value)}
                required
              />
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Trading costs</legend>
              <p className="text-xs text-muted-foreground">
                Charged on both sides of every round trip. Leave at 0 for a frictionless run.
              </p>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label htmlFor="bt-commission" className="text-xs">
                    Commission (bps)
                  </Label>
                  <Input
                    id="bt-commission"
                    type="number"
                    min="0"
                    max="1000"
                    step="1"
                    value={commissionBps}
                    onChange={(e) => setCommissionBps(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="bt-slippage" className="text-xs">
                    Slippage (bps)
                  </Label>
                  <Input
                    id="bt-slippage"
                    type="number"
                    min="0"
                    max="1000"
                    step="1"
                    value={slippageBps}
                    onChange={(e) => setSlippageBps(e.target.value)}
                  />
                </div>
              </div>
            </fieldset>

            <div className="space-y-2">
              <Label htmlFor="bt-strategy">Strategy</Label>
              <select
                id="bt-strategy"
                value={strategyType}
                onChange={(e) => setStrategyType(e.target.value as StrategyType)}
                className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="rsi_threshold">RSI threshold</option>
                <option value="sma_crossover">SMA crossover</option>
              </select>
            </div>

            {strategyType === "rsi_threshold" ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="bt-buy-below">Buy below RSI</Label>
                  <Input
                    id="bt-buy-below"
                    type="number"
                    min="0"
                    max="100"
                    value={buyBelow}
                    onChange={(e) => setBuyBelow(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="bt-sell-above">Sell above RSI</Label>
                  <Input
                    id="bt-sell-above"
                    type="number"
                    min="0"
                    max="100"
                    value={sellAbove}
                    onChange={(e) => setSellAbove(e.target.value)}
                    required
                  />
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="bt-short">Short window</Label>
                  <Input
                    id="bt-short"
                    type="number"
                    min="1"
                    max="500"
                    value={shortWindow}
                    onChange={(e) => setShortWindow(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="bt-long">Long window</Label>
                  <Input
                    id="bt-long"
                    type="number"
                    min="2"
                    max="500"
                    value={longWindow}
                    onChange={(e) => setLongWindow(e.target.value)}
                    required
                  />
                </div>
              </div>
            )}

            {error ? (
              <p className="text-sm text-red-500" role="alert">
                {error}
              </p>
            ) : null}

            <Button type="submit" disabled={pending} className="w-full">
              {pending ? "Running…" : "Run backtest"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="lg:col-span-2">
        {result === null ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Configure a strategy and run a backtest to see results here.
            </CardContent>
          </Card>
        ) : result.equity_curve.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No bars stored for {result.ticker} in that date range. Try a wider window.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Total return</p>
                  <p
                    className={`mt-1 font-mono text-xl ${
                      result.summary.total_return >= 0 ? "text-green-500" : "text-red-500"
                    }`}
                  >
                    {fmtPct(result.summary.total_return)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Final NAV</p>
                  <p className="mt-1 font-mono text-xl">{fmtCurrency(result.summary.final_nav)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Sharpe</p>
                  <p className="mt-1 font-mono text-xl">{result.summary.sharpe.toFixed(2)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Max drawdown</p>
                  <p className="mt-1 font-mono text-xl text-red-500">
                    -{(result.summary.max_drawdown * 100).toFixed(2)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Buy &amp; hold</p>
                  <p className="mt-1 font-mono text-xl">
                    {fmtPct(result.summary.benchmark_return)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">vs buy &amp; hold</p>
                  <p
                    className={`mt-1 font-mono text-xl ${
                      result.summary.excess_return >= 0 ? "text-green-500" : "text-red-500"
                    }`}
                  >
                    {result.summary.excess_return >= 0 ? "+" : ""}
                    {result.summary.excess_return.toFixed(2)} pts
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">Trading costs</p>
                  <p className="mt-1 font-mono text-xl">
                    {fmtCurrency(result.summary.total_costs)}
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="rounded-lg border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-muted-foreground">Equity curve</h2>
              <EquityCurve points={result.equity_curve} />
            </div>

            <div>
              <h2 className="mb-3 text-sm font-medium text-muted-foreground">
                Trade log ({result.trades.length})
              </h2>
              {result.trades.length === 0 ? (
                <Card>
                  <CardContent className="p-6 text-sm text-muted-foreground">
                    The strategy never triggered a trade over this window.
                  </CardContent>
                </Card>
              ) : (
                <div className="rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead className="w-[80px]">Side</TableHead>
                        <TableHead className="text-right">Price</TableHead>
                        <TableHead className="text-right">Shares</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.trades.map((t, i) => (
                        <TableRow key={`${t.date}-${t.side}-${i}`}>
                          <TableCell className="text-muted-foreground">{t.date}</TableCell>
                          <TableCell
                            className={`font-medium uppercase ${
                              t.side === "buy" ? "text-green-500" : "text-red-500"
                            }`}
                          >
                            {t.side}
                          </TableCell>
                          <TableCell className="text-right font-mono">
                            {fmtCurrency(t.price)}
                          </TableCell>
                          <TableCell className="text-right font-mono">
                            {Number(t.shares).toLocaleString("en-US", {
                              maximumFractionDigits: 4,
                            })}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
