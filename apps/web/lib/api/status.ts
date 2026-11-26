import { apiGet } from "./client";

/** `/v1/status` (OP-5, Phase 7.6): names, times and states only. */
export type ServiceStatus = {
  jobs: {
    job: string;
    status: "running" | "succeeded" | "failed" | "skipped" | string;
    started_at: string;
    finished_at: string | null;
    last_success_at: string | null;
  }[];
  aegis_sync_status: string | null;
  aegis_sync_finished_at: string | null;
  markets: { country: string; newest_bar: string | null }[];
  dead_outbox_events: number;
};

export function getServiceStatus(): Promise<ServiceStatus> {
  return apiGet<ServiceStatus>("/v1/status", { cache: "no-store" });
}

/**
 * The same report for the public footer's status strip: cached five minutes
 * and dropped with the nightly `bars` revalidation, so the footer does not
 * add an uncached API call to every public page.
 */
export function getServiceStatusCached(): Promise<ServiceStatus> {
  return apiGet<ServiceStatus>("/v1/status", { revalidateSeconds: 300, tags: ["status", "bars"] });
}
