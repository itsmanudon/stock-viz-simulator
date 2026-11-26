"use server";

import { revalidatePath } from "next/cache";

import {
  rerunExperimentRun,
  runSweep,
  runWalkForward,
  saveExperimentRun,
  saveRotationRun,
  saveStrategyRun,
} from "@/lib/api/experiments";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import type { BacktestRequest } from "@/lib/api/types";
import type { RotationRequest } from "@/lib/rotation";
import type { StrategyRequest } from "@/lib/rule-strategy";

export type SaveRunState = { runId?: number; error?: string };
export type RerunState = {
  status?: "identical" | "different" | "data_changed";
  differences?: string[];
  error?: string;
};

function detailText(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // plain text
  }
  return "The run could not be saved.";
}

function message(err: unknown, fallback: string): string {
  if (err instanceof UnauthenticatedError) return "Sign in to save and rerun backtests.";
  if (err instanceof AuthedApiError && err.status === 409) return err.message;
  return fallback;
}

/**
 * Save the run just shown (Phase 5.4), or run a walk-forward or sweep on it
 * with the default grid (5.5). The server runs it again and stores it.
 */
export async function saveBacktestRunAction(
  _prev: SaveRunState,
  formData: FormData,
): Promise<SaveRunState> {
  const kind = formData.get("kind");
  // A7.6: a run saved from `/backtest?experiment=<id>` is filed in that experiment.
  const experimentId = Number(formData.get("experiment_id")) || null;
  if (kind === "strategy" || kind === "rotation") {
    try {
      const raw = JSON.parse(String(formData.get("request") ?? ""));
      const run =
        kind === "rotation"
          ? await saveRotationRun(raw as RotationRequest, experimentId)
          : await saveStrategyRun(raw as StrategyRequest, experimentId);
      revalidatePath("/backtest/runs");
      return { runId: run.id };
    } catch (err) {
      if (err instanceof SyntaxError) return { error: "Nothing to save yet." };
      if (err instanceof AuthedApiError && [400, 404, 422].includes(err.status)) {
        return { error: detailText(err.detail) };
      }
      return { error: message(err, "The run could not be saved.") };
    }
  }
  let request: BacktestRequest;
  try {
    request = JSON.parse(String(formData.get("request") ?? "")) as BacktestRequest;
  } catch {
    return { error: "Nothing to save yet." };
  }
  const study = String(formData.get("study") ?? "single");
  try {
    const run =
      study === "walk_forward"
        ? await runWalkForward(request, experimentId)
        : study === "sweep"
          ? await runSweep(request, experimentId)
          : await saveExperimentRun(request, experimentId);
    revalidatePath("/backtest/runs");
    return { runId: run.id };
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 400) return { error: err.message };
    return { error: message(err, "The run could not be saved.") };
  }
}

export async function rerunBacktestRunAction(
  _prev: RerunState,
  formData: FormData,
): Promise<RerunState> {
  const runId = Number(formData.get("run_id"));
  if (!Number.isInteger(runId) || runId <= 0) return { error: "Invalid run." };
  try {
    const report = await rerunExperimentRun(runId);
    return { status: report.status, differences: report.differences };
  } catch (err) {
    return { error: message(err, "The rerun failed.") };
  }
}
