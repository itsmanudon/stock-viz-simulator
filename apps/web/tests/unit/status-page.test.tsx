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

const authMock = vi.fn(async (): Promise<{ user: { id: string } } | null> => null);
vi.mock("@/auth", () => ({ auth: () => authMock() }));

const brokerMock = vi.fn(async (): Promise<unknown> => null);
vi.mock("@/lib/api/brokers", () => ({ getBrokerStatusOrNull: () => brokerMock() }));

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

  it("A5.7: signed out, the Brokers section says to sign in", async () => {
    authMock.mockResolvedValueOnce(null);
    render(await StatusPage());
    expect(screen.getByRole("heading", { name: "Brokers" })).toBeVisible();
    expect(screen.getByText(/Sign in to see the broker setup/)).toBeVisible();
    expect(brokerMock).not.toHaveBeenCalled();
  });

  it("A5.7: signed in, the Brokers section shows each broker's state", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "7" } });
    brokerMock.mockResolvedValueOnce({
      brokers: [
        {
          broker: "zerodha",
          label: "Zerodha",
          provider: "kite",
          configured: false,
          state: "not_configured",
          live_data: false,
          imported_books: 1,
          last_imported_at: null,
          last_snapshot_at: null,
          last_failure_at: null,
        },
      ],
      offline_window_hours: 72,
      checked_at: "2026-11-26T10:00:00",
    });
    render(await StatusPage());
    expect(screen.getByText("Zerodha: not connected.")).toBeVisible();
    expect(
      screen.getByText("Live broker data needs a paid Kite Connect app; not set up."),
    ).toBeVisible();
  });

  it("A5.7: an unreadable broker status is a line, not an error", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "7" } });
    brokerMock.mockResolvedValueOnce(null);
    render(await StatusPage());
    expect(screen.getByText(/Broker status could not be read just now/)).toBeVisible();
    expect(screen.getByText("ingest")).toBeVisible();
  });
});
