"use client";

/**
 * A4.4: a rotation's result. Net of costs first; the report card and
 * overfitting checks; turnover; the holdings at each rebalance (who was in,
 * who came in and went out, the ranking values); the equity curve; the
 * round trips. Used by /backtest (with Save run) and a saved run's page.
 */

import Link from "next/link";
import { useState } from "react";

import { SaveStrategyRun } from "@/components/backtest-run-actions";
import { CostsDisclosure } from "@/components/costs-disclosure";
import { EquityCurve } from "@/components/equity-curve";
import { FigureStrip } from "@/components/figure-strip";
import { OverfittingChecks } from "@/components/report-card/overfitting-checks";
import { ReportCard } from "@/components/report-card/report-card";
import { ResearchEmptyState, ResearchSectionHeader } from "@/components/research-page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UniverseNote } from "@/components/universe-note";
import type { OverfittingChecks as Checks } from "@/lib/report-card";
import {
  type RotationRebalance,
  type RotationRequest,
  type RotationResult,
  nameList,
  rebalanceSummary,
  turnoverLabel,
} from "@/lib/rotation";
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

const REBALANCE_ROWS = 24;
const TRADE_ROWS = 50;
const REASON: Record<string, string> = {
  rebalance: "Left the top N",
  resize: "Trimmed to weight",
  cash_filter: "Cash filter",
  end_of_data: "Still held",
};

function Ranking({ r, topN }: { r: RotationRebalance; topN: number }) {
  const shown = (r.ranked ?? []).slice(0, topN + 5);
  if (!shown.length && !(r.unranked ?? []).length) return null;
  return (
    <details className="mt-1 text-2xs text-text-tertiary">
      <summary className="cursor-pointer hover:text-foreground">Ranking</summary>
      <ol className="mt-1 space-y-0.5 font-mono">
        {shown.map((e) => (
          <li key={e.ticker} className={e.rank <= topN ? "text-foreground" : undefined}>
            {e.rank}. {e.ticker} {e.value.toFixed(2)}
          </li>
        ))}
      </ol>
      {(r.unranked ?? []).length ? (
        <p className="mt-1">
          Not ranked:{" "}
          {(r.unranked ?? [])
            .map((u) => `${u.ticker} (${u.reason === "no_bar" ? "no bar" : "unknown"})`)
            .join(", ")}
        </p>
      ) : null}
    </details>
  );
}

export function RotationResults({
  result,
  request,
  checks,
  unlockRequest,
}: {
  result: RotationResult;
  /** The request behind the result; given on /backtest to offer Save run. */
  request?: RotationRequest;
  /** A saved run's checks (a fresh run carries its own). */
  checks?: Checks | null;
  /** The request a holdout unlock sends (defaults to ``request``). */
  unlockRequest?: RotationRequest;
}) {
  const [allRebalances, setAllRebalances] = useState(false);
  const [allTrades, setAllTrades] = useState(false);
  const currency = result.currency;
  const s = result.summary;
  const from = result.equity_curve[0]?.date;
  const to = result.equity_curve.at(-1)?.date;
  if (!from || !to) {
    return (
      <ResearchEmptyState title="No bars in that range">
        <p>Nothing is stored for these symbols in that window. Widen the dates.</p>
      </ResearchEmptyState>
    );
  }
  const rebalances = [...result.rebalances].reverse();
  const shownRebalances = allRebalances ? rebalances : rebalances.slice(0, REBALANCE_ROWS);
  const trades = [...result.trades].reverse();
  const shownTrades = allTrades ? trades : trades.slice(0, TRADE_ROWS);
  const ranking = result.rules.find((r) => r.role === "ranking");
  const filter = result.rules.find((r) => r.role === "cash_filter");
  const t = result.turnover;

  return (
    <div className="space-y-8" data-testid="rotation-results">
      <section aria-labelledby="rotation-net-heading">
        <ResearchSectionHeader
          id="rotation-net-heading"
          title="Performance, net of costs"
          description={`Top ${result.top_n} of ${result.tickers.length} symbols, ${result.schedule} · ${from} to ${to}. Every figure here is after fees, spread and slippage.`}
        />
        <FigureStrip
          label="Net performance"
          figures={[
            {
              label: "Net return",
              value: <span className={tone(s.total_return)}>{pct(s.total_return)}</span>,
            },
            {
              label: "Equal-weight hold",
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
          label="Gross, risk and turnover"
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
            {
              label: "Turnover",
              value: `${turnoverLabel(t.annualised)} a year`,
              note: `${turnoverLabel(t.mean_per_rebalance)} a rebalance`,
            },
            { label: "Rebalances", value: String(t.rebalances) },
          ]}
        />
        <ul
          className="mt-3 space-y-1 text-xs leading-5 text-text-tertiary"
          data-testid="rotation-counts"
        >
          <li>
            Ranking <span className="font-mono">{ranking?.canonical}</span>, higher first; weights{" "}
            {result.weighting === "equal" ? "equal (1/N)" : "by inverse volatility"}
            {result.buffer ? `; buffer ${result.buffer}` : ""}.
          </li>
          {filter ? (
            <li>
              Cash filter <span className="font-mono">{filter.canonical}</span> on{" "}
              {result.cash_filter_index}
              {result.cash_filter_unknown
                ? `: unknown at ${result.cash_filter_unknown} rebalances (it did not act).`
                : "."}
            </li>
          ) : null}
          <li>
            Fills {result.execution_profile}, fees {result.fee_schedule}, amounts in {currency}.{" "}
            {result.unfilled_at_end
              ? `${result.unfilled_at_end} orders were still waiting for a bar at the end.`
              : ""}
          </li>
        </ul>
        <details className="mt-2 text-xs leading-5 text-text-tertiary">
          <summary className="cursor-pointer hover:text-foreground">
            How this run was simulated
          </summary>
          <ul className="mt-1 space-y-1" data-testid="rotation-notes">
            <li>{result.timing}</li>
            {(result.notes ?? []).map((n) => (
              <li key={n}>{n}</li>
            ))}
            <li>{t.definition}</li>
          </ul>
        </details>
        <UniverseNote universe={result.universe} className="mt-1" />
        <CostsDisclosure costs={result.costs} liquidity={result.liquidity} className="mt-3" />
      </section>

      {result.window ? (
        <p className="text-xs text-text-tertiary" data-testid="run-window">
          {result.window.note}
        </p>
      ) : null}
      {result.report ? <ReportCard report={result.report} currency={currency} /> : null}
      {(checks ?? result.checks) ? (
        <OverfittingChecks
          checks={(checks ?? result.checks) as Checks}
          report={result.report}
          request={(unlockRequest ?? request) ? { rotation: unlockRequest ?? request } : undefined}
        />
      ) : null}

      {request ? <SaveStrategyRun request={request} kind="rotation" /> : null}

      <section aria-labelledby="rotation-holdings-heading">
        <ResearchSectionHeader
          id="rotation-holdings-heading"
          title={`Holdings by rebalance (${result.rebalances.length})`}
          description="Newest first. Ranked at the session's close; traded on the next session."
        />
        <div className="border-y border-border-muted">
          <Table data-testid="rotation-rebalances">
            <TableHeader>
              <TableRow>
                <TableHead>Rebalance</TableHead>
                <TableHead>Held After</TableHead>
                <TableHead className="hidden md:table-cell">In</TableHead>
                <TableHead className="hidden md:table-cell">Out</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Turnover</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shownRebalances.map((r) => (
                <TableRow
                  key={r.signal_date}
                  data-cash={r.cash_filter === true ? "true" : undefined}
                >
                  <TableCell className="whitespace-nowrap align-top text-xs">
                    {formatCloseDate(r.signal_date)}
                    <span className="block text-2xs text-text-tertiary">
                      {(r.trade_dates ?? []).length
                        ? `traded ${formatCloseDate((r.trade_dates ?? [])[0])}`
                        : "no trades"}
                    </span>
                  </TableCell>
                  <TableCell className="whitespace-normal align-top text-xs">
                    <span className="ticker font-semibold">{nameList(r.held_after ?? [])}</span>
                    <span className="block text-2xs text-text-tertiary">
                      {rebalanceSummary(r)}
                      <span className="sm:hidden">
                        {" "}
                        · turnover {turnoverLabel(r.turnover ?? 0)}
                      </span>
                    </span>
                    <span className="block text-2xs text-text-tertiary md:hidden">
                      {(r.entered ?? []).length ? `In: ${nameList(r.entered ?? [])}. ` : ""}
                      {(r.exited ?? []).length ? `Out: ${nameList(r.exited ?? [])}.` : ""}
                    </span>
                    <Ranking r={r} topN={result.top_n} />
                  </TableCell>
                  <TableCell className="hidden align-top text-xs md:table-cell">
                    {nameList(r.entered ?? [])}
                  </TableCell>
                  <TableCell className="hidden align-top text-xs text-text-secondary md:table-cell">
                    {nameList(r.exited ?? [])}
                  </TableCell>
                  <TableCell className="hidden text-right align-top font-mono text-xs sm:table-cell">
                    {turnoverLabel(r.turnover ?? 0)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {rebalances.length > REBALANCE_ROWS ? (
            <button
              type="button"
              onClick={() => setAllRebalances((v) => !v)}
              className="w-full py-2 text-xs text-text-secondary hover:text-foreground"
            >
              {allRebalances
                ? `Show the newest ${REBALANCE_ROWS}`
                : `Show all ${rebalances.length} rebalances`}
            </button>
          ) : null}
        </div>
      </section>

      <section aria-labelledby="rotation-equity-heading">
        <ResearchSectionHeader
          id="rotation-equity-heading"
          title="Equity curve"
          description={`Net NAV. Equal-weight buy and hold of the universe returned ${pct(result.benchmark.total_return)}.`}
        />
        <div className="border-y border-border-muted bg-surface-elevated p-3 sm:border-x sm:p-4">
          <EquityCurve
            points={result.equity_curve}
            currency={currency}
            accessibleLabel="Rotation equity curve, net of costs."
          />
        </div>
      </section>

      <section aria-labelledby="rotation-trades-heading">
        <ResearchSectionHeader
          id="rotation-trades-heading"
          title={`Holdings held (${result.trades.length})`}
          description="Each entry to exit, newest first. P&L is net of both legs' fees."
        />
        <div className="border-y border-border-muted">
          <Table data-testid="rotation-trades">
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Held</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
                <TableHead className="hidden sm:table-cell">Exit</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shownTrades.map((tr, i) => (
                <TableRow key={`${tr.ticker}-${tr.entry_date}-${i}`}>
                  <TableCell className="text-xs">
                    <Link
                      href={`/stocks/${encodeURIComponent(tr.ticker)}`}
                      className="ticker font-semibold hover:underline"
                    >
                      {tr.ticker}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs">
                    {formatCloseDate(tr.entry_date)} to {formatCloseDate(tr.exit_date)}
                    <span className="block font-mono text-text-tertiary">
                      {Number(tr.quantity).toLocaleString("en-US")} at{" "}
                      {money(tr.entry_price, currency)}
                    </span>
                  </TableCell>
                  <TableCell className={`text-right font-mono text-xs ${tone(Number(tr.pnl))}`}>
                    {money(tr.pnl, currency)}
                    <span className="block font-sans text-2xs text-text-tertiary sm:hidden">
                      {REASON[tr.reason]}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-xs sm:table-cell">
                    {REASON[tr.reason]}
                    {tr.open ? " (marked)" : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {trades.length > TRADE_ROWS ? (
            <button
              type="button"
              onClick={() => setAllTrades((v) => !v)}
              className="w-full py-2 text-xs text-text-secondary hover:text-foreground"
            >
              {allTrades ? `Show the newest ${TRADE_ROWS}` : `Show all ${trades.length}`}
            </button>
          ) : null}
        </div>
      </section>

      <p className="text-xs text-text-tertiary">
        Strategy <span className="font-mono">{result.strategy_hash.slice(0, 12)}</span> · data{" "}
        <span className="font-mono">{result.data_fingerprint.slice(0, 12)}</span>
      </p>
    </div>
  );
}
