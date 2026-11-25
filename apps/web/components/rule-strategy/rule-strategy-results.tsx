"use client";

/**
 * A4.1: a Rule strategy's result. Net of costs first, gross second; the
 * trades on the price chart; the equity curve; the trades table with each
 * exit's reason, the gap flag and R; what was unknown, ignored or skipped;
 * the rules as run, the stop priority and the universe stamp. Used by
 * /backtest (with Save run) and a saved run's page (without).
 */

import { useState } from "react";

import { SaveStrategyRun } from "@/components/backtest-run-actions";
import { CostsDisclosure } from "@/components/costs-disclosure";
import { EquityCurve } from "@/components/equity-curve";
import { FigureStrip } from "@/components/figure-strip";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import { StrategyTradesChart } from "@/components/rule-strategy/strategy-trades-chart";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UniverseNote } from "@/components/universe-note";
import { partialLabel } from "@/lib/fees";
import {
  REASON_LABEL,
  type StrategyRequest,
  type StrategyResult,
  formatR,
} from "@/lib/rule-strategy";
import { formatCloseDate } from "@/lib/stock-workspace";

function money(raw: string | number, currency: string): string {
  return Number(raw).toLocaleString("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  });
}

function pct(fraction: number): string {
  const v = fraction * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function tone(value: number): string {
  return value > 0 ? "text-positive" : value < 0 ? "text-negative" : "text-foreground";
}

const TRADE_ROWS = 50;

const SIZING_LABEL = {
  all_in: "all in",
  fixed_fraction: "fixed fraction of equity",
  fixed_risk: "fixed risk per trade",
} as const;

export function RuleStrategyResults({
  result,
  request,
}: {
  result: StrategyResult;
  /** The request behind the result; given on /backtest to offer Save run. */
  request?: StrategyRequest;
}) {
  const [showAll, setShowAll] = useState(false);
  const currency = result.currency;
  const s = result.summary;
  const from = result.equity_curve[0]?.date;
  const to = result.equity_curve.at(-1)?.date;
  if (!from || !to) {
    return (
      <ResearchEmptyState title="No bars in that range">
        <p>Nothing is stored for {result.tickers.join(", ")} in that window. Widen the dates.</p>
      </ResearchEmptyState>
    );
  }
  const withR = result.trades.filter((t) => t.r_multiple !== null && t.r_multiple !== undefined);
  const meanR = withR.length
    ? withR.reduce((sum, t) => sum + (t.r_multiple ?? 0), 0) / withR.length
    : null;

  return (
    <div className="space-y-8" data-testid="strategy-results">
      <section aria-labelledby="strategy-net-heading">
        <ResearchSectionHeader
          id="strategy-net-heading"
          title="Performance, net of costs"
          description={`${result.tickers.length === 1 ? result.tickers[0] : `${result.tickers.length} symbols`} · ${from} to ${to}. Every figure here is after fees, spread and slippage.`}
        />
        <FigureStrip
          label="Net performance"
          figures={[
            {
              label: "Net return",
              value: <span className={tone(s.total_return)}>{pct(s.total_return)}</span>,
            },
            {
              label:
                result.benchmark.kind === "buy_and_hold" ? "Buy and hold" : "Equal-weight hold",
              value: (
                <span className={tone(s.benchmark_return ?? 0)}>
                  {pct(s.benchmark_return ?? 0)}
                </span>
              ),
            },
            {
              label: "Excess",
              value: `${(s.excess_return ?? 0) >= 0 ? "+" : ""}${(s.excess_return ?? 0).toFixed(2)} pts`,
              note: "net minus hold",
            },
            { label: "Final NAV", value: money(s.final_nav, currency) },
          ]}
        />
        <FigureStrip
          className="mt-3"
          label="Gross and risk"
          figures={[
            { label: "Gross return", value: pct(s.gross_return ?? 0), note: "before costs" },
            {
              label: "Costs",
              value: money(s.total_costs ?? 0, currency),
              note: `fees ${money(s.total_fees ?? 0, currency)}`,
            },
            { label: "Sharpe", value: s.sharpe.toFixed(2) },
            {
              label: "Max drawdown",
              value: <span className="text-negative">-{(s.max_drawdown * 100).toFixed(2)}%</span>,
            },
            { label: "Trades", value: String(result.trades.length) },
            {
              label: "Mean R",
              value: formatR(meanR),
              note: withR.length ? `${withR.length} with a stop` : "no price stop",
            },
          ]}
        />
        <ul
          className="mt-3 space-y-1 text-xs leading-5 text-text-tertiary"
          data-testid="strategy-counts"
        >
          <li>
            {result.unknown_entry_bars} bars with an unknown entry signal and{" "}
            {result.unknown_exit_bars} with an unknown exit signal: no action on those bars.
          </li>
          <li>
            {result.ignored_entry_signals} entry signals while already holding were ignored (no
            pyramiding); {result.skipped_entries} skipped.
          </li>
          <li>
            Sizing: {SIZING_LABEL[result.sizing.kind ?? "all_in"]}. Fills {result.execution_profile}
            , fees {result.fee_schedule}, amounts in {currency}. Warm-up: {result.warmup_bars} bars
            before the start.
          </li>
        </ul>
        <details className="mt-2 text-xs leading-5 text-text-tertiary">
          <summary className="cursor-pointer hover:text-foreground">
            How this run was simulated
          </summary>
          <ul className="mt-1 space-y-1" data-testid="strategy-notes">
            {(result.notes ?? []).map((n) => (
              <li key={n}>{n}</li>
            ))}
            <li>{result.stop_priority}</li>
          </ul>
        </details>
        <UniverseNote universe={result.universe} className="mt-1" />
        <CostsDisclosure costs={result.costs} liquidity={result.liquidity} className="mt-3" />
      </section>

      {request ? <SaveStrategyRun request={request} /> : null}

      <section aria-labelledby="strategy-chart-heading">
        <ResearchSectionHeader id="strategy-chart-heading" title="Trades on the chart" />
        <div className="border-y border-border-muted bg-surface-elevated p-3 sm:border-x sm:p-4">
          <StrategyTradesChart
            tickers={result.tickers}
            trades={result.trades}
            from={from}
            to={to}
          />
        </div>
      </section>

      <section aria-labelledby="strategy-equity-heading">
        <ResearchSectionHeader
          id="strategy-equity-heading"
          title="Equity curve"
          description={`Net NAV. ${result.benchmark.kind === "buy_and_hold" ? "Buy and hold" : "Equal-weight buy and hold"} returned ${pct(result.benchmark.total_return)}.`}
        />
        <div className="border-y border-border-muted bg-surface-elevated p-3 sm:border-x sm:p-4">
          <EquityCurve
            points={result.equity_curve}
            currency={currency}
            accessibleLabel="Rule strategy equity curve, net of costs."
          />
        </div>
      </section>

      <section aria-labelledby="strategy-trades-heading">
        <ResearchSectionHeader
          id="strategy-trades-heading"
          title={`Trades (${result.trades.length})`}
          description="P&L is net of both legs' fees. R is P&L over the risk to the initial stop."
        />
        {result.trades.length === 0 ? (
          <p className="border-y border-border-muted py-6 text-sm text-text-secondary">
            The entry rule never led to a trade in this window.
          </p>
        ) : (
          <div className="border-y border-border-muted">
            <Table data-testid="strategy-trades">
              <TableHeader>
                <TableRow>
                  {result.tickers.length > 1 ? <TableHead>Symbol</TableHead> : null}
                  <TableHead>Entry</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead className="hidden text-right md:table-cell">Qty</TableHead>
                  <TableHead className="text-right">P&amp;L</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">R</TableHead>
                  <TableHead className="hidden sm:table-cell">Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(showAll ? result.trades : result.trades.slice(0, TRADE_ROWS)).map((t, i) => (
                  <TableRow key={`${t.ticker}-${t.entry_date}-${i}`} data-reason={t.reason}>
                    {result.tickers.length > 1 ? (
                      <TableCell className="ticker font-semibold">{t.ticker}</TableCell>
                    ) : null}
                    <TableCell className="text-xs">
                      {formatCloseDate(t.entry_date)}
                      <span className="block font-mono text-text-tertiary">
                        {t.direction === "short" ? "Short " : ""}
                        {money(t.entry_price, currency)}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">
                      {formatCloseDate(t.exit_date)}
                      <span className="block font-mono text-text-tertiary">
                        {money(t.exit_price, currency)}
                        {t.open ? " (marked)" : ""}
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-right font-mono md:table-cell">
                      {Number(t.quantity).toLocaleString("en-US")}
                    </TableCell>
                    <TableCell className={`text-right font-mono ${tone(Number(t.pnl))}`}>
                      {money(t.pnl, currency)}
                      {t.requested_quantity ? (
                        <span
                          className="block font-sans text-2xs text-warning"
                          data-testid="partial-fill"
                        >
                          {partialLabel(t.quantity, t.requested_quantity)}
                        </span>
                      ) : null}
                      {t.exit_adv_pct ? (
                        <span className="block font-sans text-2xs text-warning">
                          exit {t.exit_adv_pct.toFixed(1)}% of ADV
                        </span>
                      ) : null}
                      <span className="block font-sans text-2xs text-text-tertiary sm:hidden">
                        {REASON_LABEL[t.reason]}
                        {t.gap ? " (gap)" : ""} · {formatR(t.r_multiple)}
                      </span>
                    </TableCell>
                    <TableCell className="hidden text-right font-mono sm:table-cell">
                      {formatR(t.r_multiple)}
                    </TableCell>
                    <TableCell className="hidden text-xs sm:table-cell">
                      {REASON_LABEL[t.reason]}
                      {t.gap ? (
                        <span
                          className="ml-1 rounded-sm border border-border-muted px-1 text-2xs"
                          title="The bar opened through the stop, so it filled at the open"
                          data-testid="gap-flag"
                        >
                          gap
                        </span>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {result.trades.length > TRADE_ROWS ? (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="w-full py-2 text-xs text-text-secondary hover:text-foreground"
              >
                {showAll
                  ? `Show the first ${TRADE_ROWS}`
                  : `Show all ${result.trades.length} trades`}
              </button>
            ) : null}
          </div>
        )}
      </section>

      <section aria-labelledby="strategy-rules-heading" className="space-y-1 text-xs">
        <h3 id="strategy-rules-heading" className="text-sm font-semibold">
          Rules as run
        </h3>
        {result.rules.map((r) => (
          <p key={r.role}>
            <span className="text-text-tertiary">{r.role === "entry" ? "Entry" : "Exit"}:</span>{" "}
            <span className="font-mono">{r.canonical}</span>
            {r.setup_version_id ? (
              <span className="text-text-tertiary"> · setup version {r.setup_version_id}</span>
            ) : null}
          </p>
        ))}
        <p className="text-text-tertiary">
          Strategy <span className="font-mono">{result.strategy_hash.slice(0, 12)}</span> · data{" "}
          <span className="font-mono">{result.data_fingerprint.slice(0, 12)}</span>
        </p>
      </section>
    </div>
  );
}
