import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/status", () => ({
  getServiceStatus: vi.fn(async () => ({
    jobs: [
      {
        job: "ingest",
        status: "failed",
        started_at: "2026-11-12T22:00:00",
        finished_at: "2026-11-12T22:04:00",
        last_success_at: "2026-11-11T22:20:00",
      },
      {
        job: "fx",
        status: "succeeded",
        started_at: "2026-11-12T22:05:00",
        finished_at: "2026-11-12T22:06:00",
        last_success_at: "2026-11-12T22:06:00",
      },
    ], // fmt
    aegis_sync_status: "succeeded",
    aegis_sync_finished_at: "2026-11-12T22:10:00",
    markets: [{ country: "IN", newest_bar: "2026-11-12" }],
    dead_outbox_events: 0,
  })),
}));

import StatusPage from "@/app/(product)/status/page";

describe("/status (OP-5)", () => {
  it("names failing jobs with their last success, and markets by name", async () => {
    render(await StatusPage());
    expect(screen.getByText(/1 failing/)).toBeVisible();
    expect(screen.getByText("ingest")).toBeVisible();
    expect(screen.getByText(/last success Nov 11, 2026/)).toBeVisible();
    expect(screen.getByText("India")).toBeVisible();
    expect(screen.getByText("Nov 12, 2026")).toBeVisible();
  });
});
