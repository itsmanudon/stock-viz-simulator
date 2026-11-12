/**
 * /backtest/runs — the signed-in user's saved backtests (Phase 5.4).
 *
 * Each row is a stored run: request, kernel profile, fee schedule, the data
 * it read (bar count and range) and its summary. "Rerun" replays it on
 * today's data and says whether the result is identical, different, or not
 * comparable because the data changed.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { RerunBacktestRun } from "@/components/backtest-run-actions";
import { DataTableFrame } from "@/components/data-table";
import { PageEmptyState, PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatUtcDateTime } from "@/lib/api-time";
import { listExperimentRuns } from "@/lib/api/experiments";

export const metadata: Metadata = { title: "Saved backtests" };

function pct(fraction: number): string {
  return `${(fraction * 100).toFixed(2)}%`;
}

export default async function SavedBacktestsPage() {
  const runs = await listExperimentRuns();
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Research"
        title="Saved backtests"
        description="Every saved run keeps its request, rules, fees and a fingerprint of the data it read, so it can be rerun and checked."
      />
      {runs.length === 0 ? (
        <PageEmptyState title="No saved runs yet.">
          <p>Run a backtest and choose Save run.</p>
          <Button asChild className="mt-3">
            <Link href="/backtest">Open Backtest</Link>
          </Button>
        </PageEmptyState>
      ) : (
        <DataTableFrame>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Saved</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead className="hidden md:table-cell">Rules</TableHead>
                <TableHead className="text-right">Return</TableHead>
                <TableHead className="hidden text-right sm:table-cell">vs hold</TableHead>
                <TableHead className="hidden md:table-cell">Data</TableHead>
                <TableHead>Check</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.id}>
                  <TableCell className="text-muted-foreground">
                    {formatUtcDateTime(run.created_at)}
                  </TableCell>
                  <TableCell>
                    <Link href={`/backtest/runs/${run.id}`} className="ticker font-semibold">
                      {run.ticker}
                    </Link>
                    <span className="ml-2 text-2xs text-text-tertiary">
                      {run.kind === "walk_forward"
                        ? "walk-forward"
                        : run.kind === "sweep"
                          ? "sweep"
                          : "backtest"}
                    </span>
                  </TableCell>
                  <TableCell className="hidden text-xs md:table-cell">
                    {run.execution_profile} · fees {run.fee_schedule}
                  </TableCell>
                  <TableCell className="text-right font-mono" data-financial>
                    {pct(run.summary.total_return)}
                  </TableCell>
                  <TableCell className="hidden text-right font-mono sm:table-cell" data-financial>
                    {run.summary.excess_return >= 0 ? "+" : ""}
                    {run.summary.excess_return.toFixed(2)} pts
                  </TableCell>
                  <TableCell className="hidden text-xs md:table-cell">
                    {run.bar_count} bars ·{" "}
                    <span title={run.dataset_fingerprint}>
                      {run.dataset_fingerprint.slice(0, 10)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <RerunBacktestRun runId={run.id} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableFrame>
      )}
    </div>
  );
}
