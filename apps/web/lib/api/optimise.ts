/** A7.11 (M10.6): run the public optimiser (server side). */

import type { OptimiseRequest, OptimiseResult } from "../optimise";
import { apiPost } from "./client";

export function runOptimise(body: OptimiseRequest): Promise<OptimiseResult> {
  return apiPost<OptimiseResult>("/v1/research/optimise", body);
}
