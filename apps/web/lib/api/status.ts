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
