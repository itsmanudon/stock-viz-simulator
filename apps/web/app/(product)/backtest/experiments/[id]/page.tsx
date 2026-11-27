/**
 * /backtest/experiments/[id] — A7.6 (M7.7): one experiment's hypothesis and
 * the runs filed in it, each with its data fingerprint and a rerun check.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { RerunBacktestRun } from "@/components/backtest-run-actions";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { formatUtcDateTime } from "@/lib/api-time";
import { listExperimentRunsIn, listExperiments } from "@/lib/api/experiments";

export const metadata: Metadata = { title: "Experiment" };

export default async function ExperimentPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  const experiment = (await listExperiments()).find((e) => e.id === id);
  if (!experiment) notFound();
  const runs = await listExperimentRunsIn(id);
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        title={experiment.name}
        description={experiment.hypothesis ?? "No hypothesis written."}
        meta={
          <Button asChild size="sm">
            <Link href={`/backtest?experiment=${id}`}>Run a backtest into it</Link>
          </Button>
        }
      />
      {runs.length === 0 ? (
        <p className="text-sm text-text-secondary">
          No runs filed yet. Open Backtest from the button above and save a run: it is filed here.
        </p>
      ) : (
        <ul className="space-y-3" data-testid="experiment-runs">
          {runs.map((run) => (
            <li key={run.id} className="space-y-2 rounded-lg border border-border-muted p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <Link href={`/backtest/runs/${run.id}`} className="font-semibold hover:underline">
                  Run {run.id} · {run.ticker} · {run.kind.replace("_", "-")}
                </Link>
                <span className="text-xs text-text-tertiary">
                  {formatUtcDateTime(run.created_at)}
                </span>
              </div>
              <p className="font-mono text-xs text-text-tertiary">
                Data {run.dataset_fingerprint.slice(0, 12)} · {run.bar_count} bars · code{" "}
                {run.code_version.slice(0, 7)}
              </p>
              <RerunBacktestRun runId={run.id} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
