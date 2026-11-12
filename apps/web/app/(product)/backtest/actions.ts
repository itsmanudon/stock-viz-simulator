"use server";

import { revalidatePath } from "next/cache";

import { rerunExperimentRun, saveExperimentRun } from "@/lib/api/experiments";
import { AuthedApiError, UnauthenticatedError } from "@/lib/api/server";
import type { BacktestRequest } from "@/lib/api/types";

export type SaveRunState = { runId?: number; error?: string };
export type RerunState = {
  status?: "identical" | "different" | "data_changed";
  differences?: string[];
  error?: string;
};

function message(err: unknown, fallback: string): string {
  if (err instanceof UnauthenticatedError) return "Sign in to save and rerun backtests.";
  if (err instanceof AuthedApiError && err.status === 409) return err.message;
  return fallback;
}

/** Save the run just shown (Phase 5.4). The server runs it again and stores it. */
export async function saveBacktestRunAction(
  _prev: SaveRunState,
  formData: FormData,
): Promise<SaveRunState> {
  let request: BacktestRequest;
  try {
    request = JSON.parse(String(formData.get("request") ?? "")) as BacktestRequest;
  } catch {
    return { error: "Nothing to save yet." };
  }
  try {
    const run = await saveExperimentRun(request);
    revalidatePath("/backtest/runs");
    return { runId: run.id };
  } catch (err) {
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
