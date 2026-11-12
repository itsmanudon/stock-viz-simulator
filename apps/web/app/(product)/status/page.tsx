/**
 * /status — what the nightly run left behind (audit OP-5, Phase 7.6).
 *
 * Public by the owner's choice: each nightly job's last run and result, the
 * Aegis sync, the newest stored bar per market and dead outbox events.
 * Names, times and states only. Times are UTC and say so.
 */

import type { Metadata } from "next";

import { PageFrame } from "@/components/page-frame";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { formatUtcDateTime } from "@/lib/api-time";
import { type ServiceStatus, getServiceStatus } from "@/lib/api/status";
import { formatCloseDate } from "@/lib/stock-workspace";

export const metadata: Metadata = { title: "Status" };
export const dynamic = "force-dynamic";

const MARKET: Record<string, string> = {
  US: "United States",
  IN: "India",
  GB: "United Kingdom",
  DE: "Germany",
  JP: "Japan",
  CA: "Canada",
};

function tone(status: string): "positive" | "negative" | "warning" | "neutral" {
  if (status === "succeeded") return "positive";
  if (status === "failed") return "negative";
  if (status === "running") return "warning";
  return "neutral";
}

export default async function StatusPage() {
  let data: ServiceStatus | null = null;
  try {
    data = await getServiceStatus();
  } catch {
    data = null;
  }
  const failing = data?.jobs.filter((j) => j.status === "failed").length ?? 0;

  return (
    <PageFrame width="workstation" className="py-5 sm:py-7">
      <PageHeader
        eyebrow="System"
        title="Status"
        description="What the nightly run left behind: each job's last result, the news sync and the newest stored close per market. Prices are end of day; nothing here is live."
      />
      {data === null ? (
        <p className="mt-6 text-sm text-negative" role="alert">
          The API did not answer. It may be waking up; reload in a minute.
        </p>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <section
            aria-labelledby="jobs-heading"
            className="rounded-md border border-border-muted bg-card"
          >
            <h2
              id="jobs-heading"
              className="border-b border-border-muted px-4 py-3 text-sm font-semibold"
            >
              Nightly jobs{" "}
              <span className="font-normal text-text-tertiary">
                · {failing ? `${failing} failing` : "none failing"}
              </span>
            </h2>
            <ul className="divide-y divide-border-muted">
              {data.jobs.map((job) => (
                <li
                  key={job.job}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm"
                >
                  <span className="font-mono text-xs">{job.job}</span>
                  <span className="flex items-center gap-3 text-xs text-text-tertiary">
                    <span>
                      {job.status === "succeeded"
                        ? `finished ${formatUtcDateTime(job.finished_at ?? job.started_at)}`
                        : `last success ${job.last_success_at ? formatUtcDateTime(job.last_success_at) : "never"}`}
                    </span>
                    <StatusBadge label={job.status} tone={tone(job.status)} />
                  </span>
                </li>
              ))}
              {data.jobs.length === 0 ? (
                <li className="px-4 py-3 text-sm text-text-tertiary">No runs recorded yet.</li>
              ) : null}
            </ul>
          </section>
          <div className="space-y-4">
            <section
              aria-labelledby="markets-heading"
              className="rounded-md border border-border-muted bg-card p-4"
            >
              <h2 id="markets-heading" className="text-sm font-semibold">
                Newest stored close
              </h2>
              <ul className="mt-2 space-y-1.5 text-sm">
                {data.markets.map((m) => (
                  <li key={m.country} className="flex justify-between gap-3">
                    <span>{MARKET[m.country] ?? m.country}</span>
                    <span className="text-text-secondary">
                      {m.newest_bar ? formatCloseDate(m.newest_bar) : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <section
              aria-labelledby="aegis-heading"
              className="rounded-md border border-border-muted bg-card p-4 text-sm"
            >
              <h2 id="aegis-heading" className="font-semibold">
                News sync (Aegis)
              </h2>
              <p className="mt-2 text-text-secondary">
                {data.aegis_sync_status
                  ? `${data.aegis_sync_status}${data.aegis_sync_finished_at ? `, ${formatUtcDateTime(data.aegis_sync_finished_at)}` : ""}`
                  : "No sync recorded."}
              </p>
              <p className="mt-3 text-text-secondary">
                Undeliverable events: <span className="font-mono">{data.dead_outbox_events}</span>
              </p>
            </section>
          </div>
        </div>
      )}
    </PageFrame>
  );
}
