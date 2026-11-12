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

/** "Save run" under a backtest result (Phase 5.4). */
export function SaveBacktestRun({ request }: { request: BacktestRequest }) {
  const [state, save, saving] = useActionState<SaveRunState, FormData>(saveBacktestRunAction, {});
  return (
    <form action={save} className="flex flex-wrap items-center gap-3">
      <input type="hidden" name="request" value={JSON.stringify(request)} />
      <Button type="submit" variant="outline" disabled={saving || state.runId !== undefined}>
        {saving ? "Saving…" : state.runId !== undefined ? "Saved" : "Save run"}
      </Button>
      {state.runId !== undefined ? (
        <output className="text-sm">
          Saved as run {state.runId}. <Link href="/backtest/runs">See saved runs</Link>
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
