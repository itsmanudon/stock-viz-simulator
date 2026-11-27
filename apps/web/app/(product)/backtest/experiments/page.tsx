/**
 * /backtest/experiments — A7.6 (M7.7): named experiments, each a hypothesis
 * written before its runs, with the runs filed in it (`/backtest?experiment=`
 * saves into one). Every run keeps its request and data fingerprint, so its
 * rerun says identical, different or data changed.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { ExperimentForm } from "@/components/experiment-form";
import { PageHeader } from "@/components/page-header";
import { formatUtcDateTime } from "@/lib/api-time";
import { type Experiment, listExperiments } from "@/lib/api/experiments";
import { UnauthenticatedError } from "@/lib/api/server";

export const metadata: Metadata = { title: "Experiments" };

export default async function ExperimentsPage() {
  let experiments: Experiment[] | null = [];
  try {
    experiments = await listExperiments();
  } catch (err) {
    if (!(err instanceof UnauthenticatedError)) throw err;
    experiments = null;
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        title="Experiments"
        description="Write the hypothesis first, then file every run that tests it. Reruns check the result against the data it read."
      />
      {experiments === null ? (
        <p className="text-sm text-text-secondary">
          <Link href="/login?next=/backtest/experiments" className="underline">
            Sign in
          </Link>{" "}
          to keep experiments.
        </p>
      ) : (
        <>
          <section aria-labelledby="new-exp" className="max-w-xl space-y-3">
            <h2 id="new-exp" className="text-base font-semibold tracking-tight">
              New experiment
            </h2>
            <ExperimentForm />
          </section>
          <section aria-labelledby="exp-list" className="space-y-3">
            <h2 id="exp-list" className="text-base font-semibold tracking-tight">
              Your experiments
            </h2>
            {experiments.length === 0 ? (
              <p className="text-sm text-text-secondary">None yet.</p>
            ) : (
              <ul className="space-y-2" data-testid="experiment-list">
                {experiments.map((e) => (
                  <li key={e.id} className="rounded-lg border border-border-muted p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <Link
                        href={`/backtest/experiments/${e.id}`}
                        className="font-semibold hover:underline"
                      >
                        {e.name}
                      </Link>
                      <span className="text-xs text-text-tertiary">
                        {e.run_count} run{e.run_count === 1 ? "" : "s"} ·{" "}
                        {formatUtcDateTime(e.created_at)}
                      </span>
                    </div>
                    {e.hypothesis ? (
                      <p className="mt-1 text-sm text-text-secondary">{e.hypothesis}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
