/**
 * /backtest/runs/[runId] — one stored run (Phase 5.4, 5.5).
 *
 * A walk-forward shows each window: the setting chosen on its in-sample
 * period and how it did on the out-of-sample year that follows. Only those
 * out-of-sample years make the headline result. A sweep lists every setting
 * ranked, and says how many were tried.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { RerunBacktestRun } from "@/components/backtest-run-actions";
import { DataTableFrame } from "@/components/data-table";
import { FigureStrip } from "@/components/figure-strip";
import { MetaChip, PageHeader } from "@/components/page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatUtcDateTime } from "@/lib/api-time";
import {
  type ExperimentRun,
  type SweepResult,
  type WalkForwardResult,
  getExperimentRun,
} from "@/lib/api/experiments";
import { AuthedApiError } from "@/lib/api/server";

export const metadata: Metadata = { title: "Saved backtest" };

function pct(fraction: number): string {
  return `${(fraction * 100).toFixed(2)}%`;
}

function setting(strategy: Record<string, number | string>): string {
  if (strategy.type === "sma_crossover") {
    return `SMA ${strategy.short_window}/${strategy.long_window}`;
  }
  return `RSI < ${strategy.buy_below} buy, > ${strategy.sell_above} sell`;
}

const KIND_LABEL: Record<string, string> = {
  single: "Backtest",
  walk_forward: "Walk-forward",
  sweep: "Sweep",
};

export default async function SavedRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const id = Number(runId);
  if (!Number.isInteger(id) || id <= 0) notFound();
  let run: ExperimentRun;
  try {
    run = await getExperimentRun(id);
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 404) notFound();
    throw err;
  }
  const result = run.result;
  const kind = run.kind;
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Research"
        title={`${KIND_LABEL[kind] ?? kind} · ${run.ticker}`}
        description={`${run.execution_profile} · fees ${run.fee_schedule} · ${run.bar_count} bars read`}
        meta={<MetaChip>Saved {formatUtcDateTime(run.created_at)}</MetaChip>}
        actions={<RerunBacktestRun runId={run.id} />}
      />
      <FigureStrip
        label="Run result"
        figures={[
          {
            label: kind === "sweep" ? "Best return" : "Return",
            value: pct(run.summary.total_return),
          },
          { label: "Buy and hold", value: pct(run.summary.benchmark_return) },
          {
            label: "Excess",
            value: `${run.summary.excess_return >= 0 ? "+" : ""}${run.summary.excess_return.toFixed(2)} pts`,
          },
          { label: "Sharpe", value: run.summary.sharpe.toFixed(2) },
          { label: "Max drawdown", value: pct(run.summary.max_drawdown) },
        ]}
      />
      {kind === "walk_forward" && result ? (
        <WalkForwardTable result={result as WalkForwardResult} />
      ) : null}
      {kind === "sweep" && result ? <SweepTable result={result as SweepResult} /> : null}
      <p className="text-xs text-text-tertiary">
        Data fingerprint <span className="font-mono">{run.dataset_fingerprint}</span> · code{" "}
        {run.code_version.slice(0, 12)}. <Link href="/backtest/runs">All saved runs</Link>
      </p>
    </div>
  );
}

function WalkForwardTable({ result }: { result: WalkForwardResult }) {
  return (
    <section className="space-y-2">
      <p className="text-sm text-text-secondary">
        {result.tried} settings tried on each {result.in_sample_years}-year in-sample period, chosen
        by {result.score === "sharpe" ? "Sharpe" : "return"}, then scored on the next{" "}
        {result.out_of_sample_years} year(s). The return above counts only those scored years,
        carrying capital from one to the next.
      </p>
      <DataTableFrame>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Chosen on</TableHead>
              <TableHead>Setting</TableHead>
              <TableHead>Scored on</TableHead>
              <TableHead className="text-right">Scored return</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Trades</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.windows.map((w) => (
              <TableRow key={w.out_of_sample_from}>
                <TableCell className="text-xs">
                  {w.in_sample_from} – {w.in_sample_to}
                </TableCell>
                <TableCell>{setting(w.chosen)}</TableCell>
                <TableCell className="text-xs">
                  {w.out_of_sample_from} – {w.out_of_sample_to}
                </TableCell>
                <TableCell className="text-right font-mono" data-financial>
                  {pct(w.out_of_sample_return)}
                </TableCell>
                <TableCell className="hidden text-right font-mono sm:table-cell">
                  {w.trades}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableFrame>
    </section>
  );
}

function SweepTable({ result }: { result: SweepResult }) {
  return (
    <section className="space-y-2">
      <p className="text-sm text-text-secondary">
        Best of {result.tried} settings over the same range, ranked by{" "}
        {result.score === "sharpe" ? "Sharpe" : "return"}. The best of many tries flatters the
        strategy; a walk-forward is the fairer test.
      </p>
      <DataTableFrame>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>Setting</TableHead>
              <TableHead className="text-right">Return</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Sharpe</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Trades</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.runs.map((r, i) => (
              <TableRow key={JSON.stringify(r.strategy)}>
                <TableCell className="font-mono">{i + 1}</TableCell>
                <TableCell>{setting(r.strategy)}</TableCell>
                <TableCell className="text-right font-mono" data-financial>
                  {pct(r.summary.total_return)}
                </TableCell>
                <TableCell className="hidden text-right font-mono sm:table-cell">
                  {r.summary.sharpe.toFixed(2)}
                </TableCell>
                <TableCell className="hidden text-right font-mono sm:table-cell">
                  {r.trades}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableFrame>
    </section>
  );
}
