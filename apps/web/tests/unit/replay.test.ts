import { describe, expect, it } from "vitest";

import {
  datesDiffer,
  replayBarsToChart,
  replayErrorMessage,
  replayProgressPct,
  toReplayTimestamp,
} from "@/lib/replay";

describe("replay helpers", () => {
  it("maps progress without using future timestamps", () => {
    expect(
      replayProgressPct(
        "2024-06-03T00:00:00Z",
        "2024-06-03T00:00:00Z",
        "2024-06-05T00:00:00Z",
        "active",
      ),
    ).toBe(0);
    expect(
      replayProgressPct(
        "2024-06-03T00:00:00Z",
        "2024-06-05T00:00:00Z",
        "2024-06-05T00:00:00Z",
        "completed",
      ),
    ).toBe(100);
  });

  it("maps visible replay bars into chart candles without extra fields", () => {
    const bars = replayBarsToChart([
      {
        ts: "2024-06-03T00:00:00Z",
        open: "100",
        high: "105",
        low: "99",
        close: "104",
        volume: 10,
      },
      {
        ts: "2024-06-04T00:00:00Z",
        open: "104",
        high: "105",
        low: "101",
        close: "105",
        volume: 11,
      },
    ]);
    expect(bars.map((bar) => Number(bar.high))).toEqual([105, 105]);
    expect(Math.max(...bars.map((bar) => Number(bar.high)))).toBe(105);
  });

  it("maps API failures to product copy", () => {
    expect(replayErrorMessage(404)).toMatch(/not found/i);
    expect(replayErrorMessage(409)).toMatch(/no longer active/i);
    expect(replayErrorMessage(422)).toMatch(/cash or shares/i);
  });

  it("detects snapped date ranges", () => {
    expect(toReplayTimestamp("2020-01-04")).toBe("2020-01-04T00:00:00.000Z");
    expect(datesDiffer("2020-01-04", "2020-01-06T00:00:00Z")).toBe(true);
    expect(datesDiffer("2020-01-06", "2020-01-06T00:00:00Z")).toBe(false);
  });
});
