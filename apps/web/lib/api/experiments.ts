import "server-only";

import { authedDelete, authedGet, authedPost } from "./server";
import type { BacktestRequest, BacktestResult, BacktestSummary } from "./types";

/** A stored backtest (Phase 5.4). `result` is only on single-run reads. */
export type ExperimentRun = {
  id: number;
  experiment_id: number | null;
  parent_run_id?: number | null;
  kind: string;
  ticker: string;
  request: BacktestRequest;
  execution_profile: string;
  fee_schedule: string;
  code_version: string;
  dataset_fingerprint: string;
  bar_count: number;
  first_bar_at: string | null;
  last_bar_at: string | null;
  created_at: string;
  summary: BacktestSummary;
  result?: BacktestResult | null;
};

export type ExperimentRerun = {
  status: "identical" | "different" | "data_changed";
  stored_fingerprint: string;
  current_fingerprint: string;
  differences: string[];
};

export function saveExperimentRun(backtest: BacktestRequest): Promise<ExperimentRun> {
  return authedPost<ExperimentRun>("/v1/experiments/runs", { backtest });
}

export function listExperimentRuns(): Promise<ExperimentRun[]> {
  return authedGet<ExperimentRun[]>("/v1/experiments/runs");
}

export function rerunExperimentRun(runId: number): Promise<ExperimentRerun> {
  return authedPost<ExperimentRerun>(`/v1/experiments/runs/${runId}/rerun`);
}

export function deleteExperimentRun(runId: number): Promise<void> {
  return authedDelete(`/v1/experiments/runs/${runId}`);
}
