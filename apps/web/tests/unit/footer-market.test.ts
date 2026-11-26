import { describe, expect, it } from "vitest";

import type { ServiceStatus } from "@/lib/api/status";
import { equalWeightPath, lastPointY, linePath, statusFacts } from "@/lib/footer-market";

describe("equalWeightPath", () => {
  it("averages each session across symbols", () => {
    expect(
      equalWeightPath([
        [0, 2, 4],
        [0, -2, 8],
      ]),
    ).toEqual([0, 0, 6]);
  });

  it("returns null without series and ignores single points", () => {
    expect(equalWeightPath([])).toBeNull();
    expect(equalWeightPath([[1]])).toBeNull();
  });
});

describe("linePath", () => {
  it("spans the width and keeps every point inside the padding", () => {
    const d = linePath([0, 10, 5], 200, 40, 4);
    expect(d).toBe("M0.0 36.0 L100.0 4.0 L200.0 20.0");
    expect(lastPointY([0, 10, 5], 40, 4)).toBe(20);
  });

  it("draws a flat series across the middle without dividing by zero", () => {
    expect(linePath([3, 3], 100, 20, 4)).toBe("M0.0 16.0 L100.0 16.0");
  });
});

describe("statusFacts", () => {
  const status = (jobs: ServiceStatus["jobs"]): ServiceStatus => ({
    jobs,
    aegis_sync_status: null,
    aegis_sync_finished_at: null,
    markets: [
      { country: "US", newest_bar: "2025-04-07T00:00:00" },
      { country: "IN", newest_bar: "2025-04-04T00:00:00" },
      { country: "JP", newest_bar: "2025-04-07T00:00:00" },
    ],
    dead_outbox_events: 0,
  });
  const job = (s: string) => ({
    job: "ingest",
    status: s,
    started_at: "2026-11-26T01:00:00",
    finished_at: "2026-11-26T01:05:00",
    last_success_at: null,
  });

  it("names the US and India closes only, each with its own date", () => {
    expect(statusFacts(status([job("succeeded")])).closes).toEqual([
      { market: "US", date: "Apr 7, 2025" },
      { market: "India", date: "Apr 4, 2025" },
    ]);
  });

  it("reports the nightly refresh as ok, issue or unknown", () => {
    expect(statusFacts(status([job("succeeded"), job("skipped")])).refresh).toBe("ok");
    expect(statusFacts(status([job("succeeded"), job("failed")])).refresh).toBe("issue");
    expect(statusFacts(status([job("running")])).refresh).toBe("unknown");
    expect(statusFacts(null)).toEqual({ closes: [], refresh: "unknown" });
  });
});
