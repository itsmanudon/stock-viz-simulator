import { describe, expect, it } from "vitest";

import type { JournalMonth, JournalStats } from "@/lib/api/journal";
import {
  buildCalendar,
  currentMonthKey,
  describeDay,
  formatCompactPnl,
  formatRangeLabel,
  parseDateKey,
  parseMonthKey,
  shiftMonth,
  tintFor,
  tintScale,
  todayKey,
} from "@/lib/journal-view-model";

function stats(realized: string, tradeCount = 1, overrides: Partial<JournalStats> = {}) {
  return {
    realized_pnl: realized,
    trade_count: tradeCount,
    winning_trades: Number(realized) > 0 ? tradeCount : 0,
    losing_trades: Number(realized) < 0 ? tradeCount : 0,
    gross_profit: Number(realized) > 0 ? realized : "0",
    gross_loss: Number(realized) < 0 ? String(-Number(realized)) : "0",
    win_rate: null,
    profit_factor: null,
    ...overrides,
  } satisfies JournalStats;
}

function month(days: { date: string; realized: string; count?: number }[]): JournalMonth {
  return {
    unavailable_count: 0,
    period: { year: 2026, month: 8, first_day: "2026-08-01", last_day: "2026-08-31" },
    currency: "USD",
    summary: stats("0", 0),
    return_pct: null,
    start_nav: null,
    days: days.map((day) => ({ date: day.date, stats: stats(day.realized, day.count ?? 1) })),
    weeks: [
      { start: "2026-08-01", end: "2026-08-02", stats: stats("0", 0) },
      { start: "2026-08-03", end: "2026-08-09", stats: stats("125.00", 2) },
    ],
  };
}

describe("journal URL state", () => {
  it("uses New York today even when UTC has entered the next month", () => {
    const now = new Date("2026-09-01T01:30:00Z");
    expect(currentMonthKey(now)).toBe("2026-08");
    expect(todayKey(now)).toBe("2026-08-31");
  });

  it("rejects impossible dates and bounds navigation to supported years", () => {
    expect(parseDateKey("2026-02-29")).toBeNull();
    expect(parseDateKey("2026-04-31")).toBeNull();
    expect(parseDateKey("2028-02-29")).toBe("2028-02-29");
    expect(parseMonthKey("0000-01", "2026-09")).toBe("2026-09");
    expect(shiftMonth("1970-01", -1)).toBe("1970-01");
    expect(shiftMonth("2200-12", 1)).toBe("2200-12");
  });
  it("falls back when the month parameter is absent or malformed", () => {
    expect(parseMonthKey(undefined, "2026-09")).toBe("2026-09");
    expect(parseMonthKey("nonsense", "2026-09")).toBe("2026-09");
    expect(parseMonthKey("2026-13", "2026-09")).toBe("2026-09");
    expect(parseMonthKey("2026-08", "2026-09")).toBe("2026-08");
  });

  it("rejects a date parameter that isn't a plain calendar date", () => {
    expect(parseDateKey("2026-08-19")).toBe("2026-08-19");
    expect(parseDateKey("2026-8-9")).toBeNull();
    expect(parseDateKey("2026-13-01")).toBeNull();
    expect(parseDateKey(undefined)).toBeNull();
  });

  it("rolls the year when stepping past a month boundary", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-08", 3)).toBe("2026-11");
  });
});

describe("calendar grid", () => {
  it("pads a month that starts mid-week into whole Monday-first rows", () => {
    // 2026-08-01 is a Saturday, so the first row carries five padding days.
    const weeks = buildCalendar("2026-08", null, "2026-08-19");

    expect(weeks[0].days).toHaveLength(7);
    expect(weeks[0].days.filter((day) => day.inMonth).map((day) => day.date)).toEqual([
      "2026-08-01",
      "2026-08-02",
    ]);
    expect(weeks[0].days.slice(0, 5).every((day) => !day.inMonth)).toBe(true);
    expect(weeks.at(-1)?.days.some((day) => day.date === "2026-08-31")).toBe(true);
  });

  it("keeps its exact shape with no data, so nothing jumps while loading", () => {
    const withoutData = buildCalendar("2026-08", null, "2026-08-19");
    const withData = buildCalendar("2026-08", month([{ date: "2026-08-19", realized: "100" }]));

    expect(withData).toHaveLength(withoutData.length);
    expect(withData.every((week) => week.days.length === 7)).toBe(true);
  });

  it("marks weekends and attaches each day's summary", () => {
    const weeks = buildCalendar(
      "2026-08",
      month([{ date: "2026-08-03", realized: "100.00", count: 2 }]),
      "2026-08-19",
    );
    const monday = weeks[1].days[0];
    const saturday = weeks[1].days[5];

    expect(monday.date).toBe("2026-08-03");
    expect(monday.isWeekend).toBe(false);
    expect(monday.summary?.stats.trade_count).toBe(2);
    expect(saturday.isWeekend).toBe(true);
    expect(saturday.summary).toBeNull();
  });

  it("keys each row by its first in-month day so week summaries line up", () => {
    const weeks = buildCalendar("2026-08", month([]), "2026-08-19");

    expect(weeks[0].key).toBe("2026-08-01");
    expect(weeks[1].key).toBe("2026-08-03");
    expect(weeks[1].summary?.stats.realized_pnl).toBe("125.00");
  });

  it("flags today only for the matching cell", () => {
    const weeks = buildCalendar("2026-08", null, "2026-08-19");
    const flagged = weeks.flatMap((week) => week.days).filter((day) => day.isToday);

    expect(flagged.map((day) => day.date)).toEqual(["2026-08-19"]);
  });
});

describe("tint normalization", () => {
  it("anchors on the median so one outlier can't flatten the month", () => {
    const ordinary = [100, 120, 140, 160, 180];
    const withOutlier = [...ordinary, 500_000];

    // The anchor barely moves — 140 to 150, not out to 500,000 — so every
    // ordinary day keeps the tint it had.
    expect(tintScale(ordinary)).toBe(140);
    expect(tintScale(withOutlier)).toBe(150);
    for (const value of ordinary) {
      expect(tintFor(value, tintScale(withOutlier)).level).toBe(
        tintFor(value, tintScale(ordinary)).level,
      );
    }
    // And the outlier is the one day that reads as large.
    expect(tintFor(500_000, tintScale(withOutlier)).level).toBe(3);
  });

  it("ignores zero and non-finite values when picking the anchor", () => {
    expect(tintScale([0, 0, 0])).toBe(0);
    expect(tintScale([Number.NaN, 0, 50])).toBe(50);
  });

  it("separates small, medium, and large moves within one month", () => {
    // Median of the month is 1,000.
    const scale = tintScale([200, 900, 1100, 6000]);

    expect(tintScale([200, 900, 1100, 6000])).toBe(1000);
    expect(tintFor(200, scale).level).toBe(1); // 0.2x a typical day
    expect(tintFor(900, scale).level).toBe(2); // 0.9x
    expect(tintFor(6000, scale).level).toBe(3); // 6x
  });

  it("does not collapse a realistic month onto one tint level", () => {
    // The failure mode of the old log-ratio transform: everything but the
    // smallest day came out level 3.
    const days = [12, 562, 688, 845, 1234, 1562, 1711, 1953, 2318, 4108];
    const scale = tintScale(days);
    const levels = new Set(days.map((value) => tintFor(value, scale).level));

    expect(levels).toEqual(new Set([1, 2, 3]));
  });

  it("treats a scratch day as flat rather than as a gain", () => {
    expect(tintFor(0, 1000)).toEqual({ sign: "flat", level: 0 });
  });

  it("signs the tint by direction, not magnitude", () => {
    expect(tintFor(-500, 1000).sign).toBe("negative");
    expect(tintFor(500, 1000).sign).toBe("positive");
    expect(tintFor(-500, 1000).level).toBe(tintFor(500, 1000).level);
  });

  it("falls back to the lightest tint when the month has no scale", () => {
    // A single non-zero day is its own median, so it sits exactly at 1.0x.
    expect(tintFor(42, tintScale([42]))).toEqual({ sign: "positive", level: 2 });
    expect(tintFor(42, 0)).toEqual({ sign: "positive", level: 1 });
  });
});

describe("formatting", () => {
  it("abbreviates thousands for the narrow grid", () => {
    expect(formatCompactPnl(5267)).toBe("+$5.3k");
    expect(formatCompactPnl(-412)).toBe("-$412");
    expect(formatCompactPnl(0)).toBe("$0");
    expect(formatCompactPnl(-125_400)).toBe("-$125k");
  });

  it("formats a week range without repeating the year", () => {
    expect(formatRangeLabel("2026-08-03", "2026-08-09")).toBe("Aug 3 – Aug 9, 2026");
    expect(formatRangeLabel("2026-08-31", "2026-08-31")).toBe("August 31, 2026");
  });

  it("describes a day in words, so colour is never the only cue", () => {
    expect(describeDay("2026-08-19", stats("5267.00", 20))).toBe(
      "August 19, profit 5,267.00 dollars, 20 trades",
    );
    expect(describeDay("2026-08-20", stats("-412.50", 1))).toBe(
      "August 20, loss 412.50 dollars, 1 trade",
    );
    expect(describeDay("2026-08-21", null)).toBe("August 21, no closed trades");
    expect(describeDay("2026-08-22", stats("0", 3))).toBe(
      "August 22, no net gain or loss, 3 trades",
    );
  });
});
