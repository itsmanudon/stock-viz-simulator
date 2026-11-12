"use client";

/**
 * Interactive backtest experiment: setup on the left, results on the right.
 *
 * POST /v1/backtest is public, so this client island calls it from the browser.
 * The engine remains authoritative — this component only composes the UX.
 */

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { EquityCurve } from "@/components/equity-curve";
import { FigureStrip } from "@/components/figure-strip";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import { Button } from "@/components/ui/button";
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
import {
  type BacktestSymbol,
  defaultBacktestRange,
  pickBacktestTicker,
} from "@/lib/backtest-defaults";
import { formatCloseDate } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

type StrategyType = "rsi_threshold" | "sma_crossover";

const RISK_FREE_RATE = 0.05;

function fmtCurrency(raw: string, currency = "USD"): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  });
}

function fmtPct(fraction: number): string {
  const pct = fraction * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function parseApiDetail(err: ApiError): string {
  const raw = err.message.replace(/^API \d+ [^:]+:\s*/, "");
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // fall through
  }
  return raw || err.message;
}

function signedClass(value: number): string {
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-foreground";
}

export function BacktestForm({
  symbols,
  initialTicker,
}: {
  symbols: BacktestSymbol[];
  initialTicker?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const lastCloseOf = useMemo(
    () => new Map(symbols.map((item) => [item.ticker, item.lastClose])),
    [symbols],
  );
  const startingTicker = pickBacktestTicker(symbols, initialTicker);
  const startingRange = defaultBacktestRange(lastCloseOf.get(startingTicker));

  const [ticker, setTicker] = useState(startingTicker);
  const [from, setFrom] = useState(startingRange.from);
  const [to, setTo] = useState(startingRange.to);
  // Until the dates are edited by hand, they follow the chosen symbol.
  const [datesEdited, setDatesEdited] = useState(false);
  const lastClose = lastCloseOf.get(ticker);
  const [initialCash, setInitialCash] = useState("100000");
  const [strategyType, setStrategyType] = useState<StrategyType>("rsi_threshold");
  const [buyBelow, setBuyBelow] = useState("30");
  const [sellAbove, setSellAbove] = useState("70");
  const [shortWindow, setShortWindow] = useState("20");
  const [longWindow, setLongWindow] = useState("50");
  const [commissionBps, setCommissionBps] = useState("0");
  const [returnMode, setReturnMode] = useState<"price" | "total">("price");
  const [fillRule, setFillRule] = useState<"next_open" | "next_close">("next_open");
  const [spreadBps, setSpreadBps] = useState("0");
  const [feeSchedule, setFeeSchedule] = useState<"none" | "us_equity_2026">("none");
  const [slippageBps, setSlippageBps] = useState("0");

  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ message: string; kind: "validation" | "system" } | null>(
    null,
  );
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [lastCosts, setLastCosts] = useState({ commissionBps: 0, slippageBps: 0 });

  function syncTicker(next: string) {
    setTicker(next);
    if (!datesEdited) {
      const range = defaultBacktestRange(lastCloseOf.get(next));
      setFrom(range.from);
      setTo(range.to);
    }
    const params = new URLSearchParams(searchParams.toString());
    params.set("ticker", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
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

    const commission = Number(commissionBps) || 0;
    const slippage = Number(slippageBps) || 0;

    try {
      const res = await runBacktest({
        ticker,
        from,
        to,
        initial_cash: initialCash,
        strategy,
        commission_bps: commission,
        slippage_bps: slippage,
        return_mode: returnMode,
        fill_rule: fillRule,
        spread_bps: Number(spreadBps) || 0,
        fee_schedule: feeSchedule,
      });
      setLastCosts({ commissionBps: commission, slippageBps: slippage });
      setResult(res);
    } catch (err) {
      setResult(null);
      if (err instanceof ApiError) {
        setError({
          message: parseApiDetail(err),
          kind: err.status >= 400 && err.status < 500 ? "validation" : "system",
        });
      } else {
        setError({ message: "Backtest failed", kind: "system" });
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mt-6 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:items-start">
      <section
        aria-labelledby="backtest-setup-heading"
        className="border-y border-border-muted sm:border-x"
      >
        <div className="border-b border-border-muted px-4 py-3">
          <h2 id="backtest-setup-heading" className="text-sm font-semibold">
            Strategy setup
          </h2>
          <p className="mt-1 text-xs leading-5 text-text-tertiary">
            Signals from a completed bar execute on the following bar to avoid same-bar look-ahead
            bias.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-5 p-4">
          <div className="space-y-2">
            <Label htmlFor="bt-ticker">Symbol</Label>
            <select
              id="bt-ticker"
              value={ticker}
              onChange={(event) => syncTicker(event.target.value)}
              required
              className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
            >
              {symbols.map((symbol) => (
                <option key={symbol.ticker} value={symbol.ticker}>
                  {symbol.ticker} — {symbol.name}
                  {symbol.lastClose === null ? " (no stored history)" : ""}
                </option>
              ))}
            </select>
            {ticker ? (
              <p className="text-xs text-text-tertiary">
                <Link href={`/stocks/${ticker}`} className="hover:underline">
                  Open {ticker} workspace
                </Link>
              </p>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="bt-from">From</Label>
              <Input
                id="bt-from"
                type="date"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                  setDatesEdited(true);
                }}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="bt-to">To</Label>
              <Input
                id="bt-to"
                type="date"
                value={to}
                onChange={(event) => {
                  setTo(event.target.value);
                  setDatesEdited(true);
                }}
                required
              />
            </div>
            {lastClose !== undefined ? (
              <p className="col-span-2 text-xs text-text-tertiary">
                {lastClose
                  ? `Stored closes for ${ticker} end ${formatCloseDate(lastClose)}.`
                  : `${ticker} has no stored closes yet, so a run returns nothing.`}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bt-cash">Initial cash</Label>
            <Input
              id="bt-cash"
              type="number"
              min="1"
              step="1"
              value={initialCash}
              onChange={(event) => setInitialCash(event.target.value)}
              required
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Trading costs</legend>
            <p className="text-xs text-text-tertiary">
              Charged on both sides of every round trip. Zero is a frictionless run, not a live
              broker model.
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
                  onChange={(event) => setCommissionBps(event.target.value)}
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
                  onChange={(event) => setSlippageBps(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="bt-spread" className="text-xs">
                  Spread (bps)
                </Label>
                <Input
                  id="bt-spread"
                  type="number"
                  min="0"
                  max="1000"
                  step="1"
                  value={spreadBps}
                  onChange={(event) => setSpreadBps(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="bt-fees" className="text-xs">
                  Regulatory fees
                </Label>
                <select
                  id="bt-fees"
                  value={feeSchedule}
                  onChange={(event) =>
                    setFeeSchedule(event.target.value as "none" | "us_equity_2026")
                  }
                  className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
                >
                  <option value="none">None</option>
                  <option value="us_equity_2026">US equity 2026 (SEC, FINRA on sales)</option>
                </select>
              </div>
            </div>
          </fieldset>

          <div className="space-y-2">
            <Label htmlFor="bt-fill-rule">Fill at</Label>
            <select
              id="bt-fill-rule"
              value={fillRule}
              onChange={(event) => setFillRule(event.target.value as "next_open" | "next_close")}
              className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
            >
              <option value="next_open">Next bar&apos;s open</option>
              <option value="next_close">Next bar&apos;s close</option>
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bt-returns">Returns</Label>
            <select
              id="bt-returns"
              value={returnMode}
              onChange={(event) => setReturnMode(event.target.value as "price" | "total")}
              className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
            >
              <option value="price">Price only (dividends not included)</option>
              <option value="total">Total return (dividends credited)</option>
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bt-strategy">Strategy</Label>
            <select
              id="bt-strategy"
              value={strategyType}
              onChange={(event) => setStrategyType(event.target.value as StrategyType)}
              className="flex h-10 w-full rounded-sm border border-input bg-transparent px-3 py-2 text-sm"
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
                  onChange={(event) => setBuyBelow(event.target.value)}
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
                  onChange={(event) => setSellAbove(event.target.value)}
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
                  onChange={(event) => setShortWindow(event.target.value)}
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
                  onChange={(event) => setLongWindow(event.target.value)}
                  required
                />
              </div>
            </div>
          )}

          {error ? (
            <div className="border border-negative/40 bg-negative/5 px-3 py-2 text-sm" role="alert">
              <p className="font-medium">
                {error.kind === "validation" ? "Check the setup" : "Run failed"}
              </p>
              <p className="mt-1 text-text-secondary">{error.message}</p>
            </div>
          ) : null}

          <Button type="submit" disabled={pending} className="w-full rounded-sm">
            {pending ? "Running…" : "Run backtest"}
          </Button>
        </form>
      </section>

      <div aria-busy={pending} aria-live="polite">
        {pending ? (
          <div className="border-y border-border-muted px-4 py-10 text-sm text-text-secondary sm:border-x sm:px-6">
            Running the rule over stored daily bars…
          </div>
        ) : result === null ? (
          <ResearchEmptyState title="No experiment yet">
            <p>
              Test RSI threshold or SMA crossover rules on stored end-of-day closes. Positions are
              all-in or all-out. This is not a brokerage-grade market-microstructure simulation.
            </p>
          </ResearchEmptyState>
        ) : result.equity_curve.length === 0 ? (
          <ResearchEmptyState title={`No bars for ${result.ticker}`}>
            <p>Nothing is stored in that date range. Widen the window or pick another symbol.</p>
          </ResearchEmptyState>
        ) : (
          <BacktestResults
            result={result}
            commissionBps={lastCosts.commissionBps}
            slippageBps={lastCosts.slippageBps}
          />
        )}
      </div>
    </div>
  );
}

/** "▲ +12.84%": a signed figure with its arrow, coloured by sign. */
function Signed({ value, text }: { value: number; text: string }) {
  return (
    <span className={signedClass(value)}>
      {value > 0 ? "▲ " : value < 0 ? "▼ " : ""}
      {text}
    </span>
  );
}

function BacktestResults({
  result,
  commissionBps,
  slippageBps,
}: {
  result: BacktestResult;
  commissionBps: number;
  slippageBps: number;
}) {
  const currency = result.currency ?? "USD";
  const totalReturn = (result.return_mode ?? "price") === "total";
  return (
    <div className="space-y-8">
      <section aria-labelledby="equity-heading">
        <ResearchSectionHeader
          id="equity-heading"
          title="Equity curve"
          description={`Strategy NAV versus the run window. Buy-and-hold benchmark return ${fmtPct(result.summary.benchmark_return)}.`}
        />
        <div className="border-y border-border-muted bg-surface-elevated p-3 sm:border-x sm:p-4">
          <EquityCurve
            points={result.equity_curve}
            accessibleLabel={`${result.ticker} strategy equity curve from the backtest run.`}
          />
        </div>
      </section>

      <section aria-labelledby="primary-metrics-heading">
        <ResearchSectionHeader id="primary-metrics-heading" title="Performance" />
        <FigureStrip
          label="Performance"
          figures={[
            {
              label: "Strategy return",
              value: (
                <Signed
                  value={result.summary.total_return}
                  text={fmtPct(result.summary.total_return)}
                />
              ),
            },
            {
              label: "Benchmark return",
              value: (
                <Signed
                  value={result.summary.benchmark_return}
                  text={fmtPct(result.summary.benchmark_return)}
                />
              ),
            },
            {
              label: "Excess return",
              value: (
                <Signed
                  value={result.summary.excess_return}
                  text={`${result.summary.excess_return >= 0 ? "+" : ""}${result.summary.excess_return.toFixed(2)} pts`}
                />
              ),
              note: "strategy minus buy-and-hold",
            },
            { label: "Final NAV", value: fmtCurrency(result.summary.final_nav, currency) },
          ]}
        />
      </section>

      <section aria-labelledby="risk-metrics-heading">
        <ResearchSectionHeader id="risk-metrics-heading" title="Risk and costs" />
        <FigureStrip
          label="Risk and costs"
          figures={[
            { label: "Sharpe", value: result.summary.sharpe.toFixed(2) },
            {
              label: "Max drawdown",
              value: (
                <span className="text-negative">
                  ▼ -{(result.summary.max_drawdown * 100).toFixed(2)}%
                </span>
              ),
            },
            { label: "Total costs", value: fmtCurrency(result.summary.total_costs, currency) },
            { label: "Trades", value: String(result.trades.length) },
          ]}
        />
        <p className="mt-3 text-xs leading-5 text-text-tertiary">
          Commission {commissionBps} bps · slippage {slippageBps} bps · Sharpe uses a{" "}
          {(RISK_FREE_RATE * 100).toFixed(0)}% annual risk-free rate. Fills use the next bar&apos;s{" "}
          {(result.execution_profile ?? "legacy_close/v1").startsWith("next_open")
            ? "open"
            : "close"}{" "}
          after a completed-bar signal ({result.execution_profile ?? "legacy_close/v1"}; fees:{" "}
          {result.fee_schedule ?? "none"}).
        </p>
        <p className="mt-1 text-xs leading-5 text-text-tertiary" data-testid="backtest-basis">
          Amounts in {currency}.{" "}
          {totalReturn
            ? "Total return: dividends are credited to shares held into each ex-date."
            : "Price return: dividends are not included."}
          {result.price_basis
            ? ` Price basis: ${result.price_basis === "mixed" ? "mixed (some bars use a different adjustment)" : result.price_basis.replaceAll("_", " ")}.`
            : ""}
          {(result.warmup_bars ?? 0) > 0
            ? ` The strategy warmed up on ${result.warmup_bars} bars before the start; trading and the benchmark begin on the start date.`
            : ""}
        </p>
      </section>

      <section aria-labelledby="trades-heading">
        <ResearchSectionHeader
          id="trades-heading"
          title={`Trade log (${result.trades.length})`}
          description="All-in / all-out fills. Price includes spread and slippage; fees are shown separately."
        />
        {result.trades.length === 0 ? (
          <p className="border-y border-border-muted py-6 text-sm text-text-secondary">
            The strategy never triggered a trade over this window.
          </p>
        ) : (
          <div className="border-y border-border-muted">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead className="w-[80px]">Side</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Shares</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Fees</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.trades.map((trade, index) => (
                  <TableRow key={`${trade.date}-${trade.side}-${index}`}>
                    <TableCell className="text-muted-foreground">{trade.date}</TableCell>
                    {/* Neutral: a buy or a sell is not a gain or a loss. */}
                    <TableCell className="font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          aria-hidden
                          className="inline-grid size-5 place-items-center rounded-md border border-border-muted bg-surface-secondary text-2xs"
                        >
                          {trade.side === "buy" ? "↗" : "↘"}
                        </span>
                        {trade.side === "buy" ? "Buy" : "Sell"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {fmtCurrency(trade.price, currency)}
                    </TableCell>
                    <TableCell className="hidden text-right font-mono sm:table-cell">
                      {Number(trade.shares).toLocaleString("en-US", {
                        maximumFractionDigits: 4,
                      })}
                    </TableCell>
                    <TableCell
                      className="hidden text-right font-mono sm:table-cell"
                      title={(trade.fees ?? []).map((f) => `${f.name} ${f.amount}`).join(", ")}
                    >
                      {fmtCurrency(
                        String((trade.fees ?? []).reduce((sum, f) => sum + Number(f.amount), 0)),
                        currency,
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
