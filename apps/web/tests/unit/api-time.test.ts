import { describe, expect, it } from "vitest";

import { apiTimestampMs, barTimeToUtcSeconds, parseApiTimestamp } from "@/lib/api-time";
import { formatReplayDate } from "@/lib/replay";
import { formatSignalDateTime } from "@/lib/signals-workspace";

// Run under TZ=Asia/Tokyo, TZ=America/Los_Angeles and TZ=UTC: the answers must
// not move. `new Date("2025-04-04T00:00:00")` gave 2025-04-03T15:00Z in Tokyo.
const APR_4_UTC_SECONDS = Date.UTC(2025, 3, 4) / 1000;

describe("API timestamps (audit RS-2)", () => {
  it("reads a zone-less bar time as UTC midnight", () => {
    expect(barTimeToUtcSeconds("2025-04-04T00:00:00")).toBe(APR_4_UTC_SECONDS);
    expect(barTimeToUtcSeconds("2025-04-04")).toBe(APR_4_UTC_SECONDS);
    expect(barTimeToUtcSeconds("2025-04-04 00:00:00")).toBe(APR_4_UTC_SECONDS);
  });

  it("keeps fractional seconds and honours an explicit zone", () => {
    expect(apiTimestampMs("2025-04-04T20:15:30.123456")).toBe(
      Date.UTC(2025, 3, 4, 20, 15, 30, 123),
    );
    expect(barTimeToUtcSeconds("2025-04-04T00:00:00Z")).toBe(APR_4_UTC_SECONDS);
    expect(barTimeToUtcSeconds("2025-04-04T09:00:00+09:00")).toBe(APR_4_UTC_SECONDS);
  });

  it("returns an invalid date for unreadable input", () => {
    expect(Number.isNaN(apiTimestampMs("not a date"))).toBe(true);
    expect(Number.isNaN(parseApiTimestamp("").getTime())).toBe(true);
  });

  it("shows a zone-less fill time as the UTC time it was stored at", () => {
    expect(formatSignalDateTime("2025-04-04T20:00:00")).toMatch(/Apr 4, 2025.*08:00 PM UTC/);
  });

  it("dates a replay bar by its stored day", () => {
    expect(formatReplayDate("2025-04-04T00:00:00")).toBe("Friday, April 4, 2025");
  });
});
