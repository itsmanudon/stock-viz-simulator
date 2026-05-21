import { apiPost } from "./client";
import type { BacktestRequest, BacktestResult } from "./types";

/**
 * Run a strategy backtest. The endpoint is public, so this is callable from
 * the browser (the /backtest form is a client component).
 */
export function runBacktest(body: BacktestRequest): Promise<BacktestResult> {
  return apiPost<BacktestResult>("/v1/backtest", body);
}
