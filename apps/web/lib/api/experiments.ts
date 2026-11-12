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
  /** `kind` "single": a BacktestResult; "walk_forward" / "sweep": their own shape. */
  result?: BacktestResult | WalkForwardResult | SweepResult | null;
};

export type WalkForwardWindow = {
  in_sample_from: string;
  in_sample_to: string;
  out_of_sample_from: string;
  out_of_sample_to: string;
  chosen: Record<string, number | string>;
  in_sample_score: number;
  out_of_sample_return: number;
  trades: number;
};

/** Phase 5.5: choose on each in-sample period, score on the next one. */
export type WalkForwardResult = {
  result_kind: "walk_forward";
  ticker: string;
  currency: string;
  score: "sharpe" | "total_return";
  in_sample_years: number;
  out_of_sample_years: number;
  step_years: number;
  tried: number;
  windows: WalkForwardWindow[];
  equity_curve: { date: string; nav: string }[];
  summary: BacktestSummary;
};

export type SweepResult = {
  result_kind: "sweep";
  ticker: string;
  currency: string;
  score: "sharpe" | "total_return";
  tried: number;
  runs: {
    strategy: Record<string, number | string>;
    score: number;
    summary: BacktestSummary;
    trades: number;
  }[];
  summary: BacktestSummary;
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

export function runWalkForward(backtest: BacktestRequest): Promise<ExperimentRun> {
  return authedPost<ExperimentRun>("/v1/experiments/walk-forward", { backtest });
}

export function runSweep(backtest: BacktestRequest): Promise<ExperimentRun> {
  return authedPost<ExperimentRun>("/v1/experiments/sweep", { backtest });
}

export function getExperimentRun(runId: number): Promise<ExperimentRun> {
  return authedGet<ExperimentRun>(`/v1/experiments/runs/${runId}`);
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
