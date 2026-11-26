import "server-only";

import type { ScanStudy, ScanStudyRequest } from "../event-study";
import { authedPost } from "./server";

/** A4.5: the scan event study as the signed-in user (watchlists, own setups). */
export function runScanEventStudyAsUser(body: ScanStudyRequest): Promise<ScanStudy> {
  return authedPost<ScanStudy>("/v1/research/scan-event-study", body);
}
