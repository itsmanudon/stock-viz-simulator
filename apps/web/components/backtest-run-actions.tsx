"use client";

import Link from "next/link";
import { useActionState } from "react";

import {
  type RerunState,
  type SaveRunState,
  rerunBacktestRunAction,
  saveBacktestRunAction,
} from "@/app/(product)/backtest/actions";
import { Button } from "@/components/ui/button";
import type { BacktestRequest } from "@/lib/api/types";

const STUDIES = [
  { study: "single", label: "Save run" },
  { study: "walk_forward", label: "Walk-forward" },
  { study: "sweep", label: "Sweep settings" },
] as const;

/**
 * Under a backtest result: save it (Phase 5.4), or test the strategy with a
 * walk-forward or a sweep over the default grid (5.5). Each is stored.
 */
export function SaveBacktestRun({ request }: { request: BacktestRequest }) {
  const [state, save, saving] = useActionState<SaveRunState, FormData>(saveBacktestRunAction, {});
  return (
    <form action={save} className="space-y-2">
      <input type="hidden" name="request" value={JSON.stringify(request)} />
      <div className="flex flex-wrap items-center gap-2">
        {STUDIES.map((s) => (
          <Button
            key={s.study}
            type="submit"
            name="study"
            value={s.study}
            variant="outline"
            disabled={saving}
          >
            {s.label}
          </Button>
        ))}
        {saving ? <output className="text-sm">Working…</output> : null}
      </div>
      <p className="text-xs leading-5 text-text-tertiary">
        Walk-forward picks the best setting on each 3-year period and scores it on the next year;
        only those scored years count. A sweep ranks every setting over the whole range.
      </p>
      {state.runId !== undefined ? (
        <output className="block text-sm">
          Stored as run {state.runId}. <Link href={`/backtest/runs/${state.runId}`}>Open it</Link>
        </output>
      ) : null}
      {state.error ? (
        <p role="alert" className="text-sm text-negative">
          {state.error}
        </p>
      ) : null}
    </form>
  );
}

const RERUN_LABEL: Record<NonNullable<RerunState["status"]>, string> = {
  identical: "Identical: same data, same result.",
  different: "Different result on the same data: the code changed how it computes.",
  data_changed: "The stored bars or dividends changed since this run; results are not compared.",
};

export function RerunBacktestRun({ runId }: { runId: number }) {
  const [state, rerun, running] = useActionState<RerunState, FormData>(rerunBacktestRunAction, {});
  return (
    <form action={rerun} className="space-y-1">
      <input type="hidden" name="run_id" value={runId} />
      <Button type="submit" size="sm" variant="outline" disabled={running}>
        {running ? "Rerunning…" : "Rerun"}
      </Button>
      {state.status ? (
        <output className="block text-xs" data-status={state.status}>
          {RERUN_LABEL[state.status]}
          {state.differences?.length ? ` Differs in: ${state.differences.join(", ")}.` : ""}
        </output>
      ) : null}
      {state.error ? (
        <p role="alert" className="text-xs text-negative">
          {state.error}
        </p>
      ) : null}
    </form>
  );
}
