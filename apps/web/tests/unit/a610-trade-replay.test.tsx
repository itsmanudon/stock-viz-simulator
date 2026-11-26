// A6.10: the trade replay player's pure helpers (running MAE/MFE, fill placement).
import { describe, expect, it } from "vitest";

import { fillBarIndex, runningExcursions } from "@/components/journal/trade-replay-player";
import type { TradeReplay } from "@/lib/api/journal-entries";

const bar = (minute: number, low: string, high: string) => ({
  ts: `2025-04-10T18:0${minute}:00`,
  open: low,
  high,
  low,
  close: high,
  volume: 10,
});

const replay: TradeReplay = {
  entry_id: 1,
  ticker: "AAPL",
  currency: "USD",
  side: "long",
  status: "closed",
  interval: "1m",
  bars_note: "Minute bars.",
  bars: [bar(0, "147", "149"), bar(1, "149", "151"), bar(2, "146", "150"), bar(3, "150", "156")],
  fills: [
    { at: "2025-04-10T18:01:20", side: "buy", quantity: "10", price: "150", time_known: true },
    { at: "2025-04-10T18:03:10", side: "sell", quantity: "10", price: "155", time_known: true },
  ],
  planned_entry: null,
  planned_stop: null,
  planned_target: null,
  excursions: {
    basis: "exact_minutes",
    note: "",
    mae: null,
    mfe: null,
    reason: null,
    missing_sessions: [],
    sessions: 1,
  } as unknown as TradeReplay["excursions"],
  hesitation: null,
};

describe("fillBarIndex", () => {
  it("places a fill in its minute", () => {
    expect(fillBarIndex(replay.bars, replay.fills[0].at, "1m")).toBe(1);
    expect(fillBarIndex(replay.bars, replay.fills[1].at, "1m")).toBe(3);
  });
});

describe("runningExcursions", () => {
  it("grows bar by bar while shares are held", () => {
    expect(runningExcursions(replay, 1)).toEqual({ mae: null, mfe: null }); // bought in bar 1
    expect(runningExcursions(replay, 2)).toEqual({ mae: -4, mfe: 0 }); // 146-150, 150-150
    expect(runningExcursions(replay, 3)).toEqual({ mae: -4, mfe: 6 }); // high 156
  });
});
