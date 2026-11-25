import { describe, expect, it } from "vitest";

import { anchorBarTime, anchorLogical, logicalToDate, periodKey } from "@/lib/drawings/anchor";
import { dragPoints, placePoint, roundPrice } from "@/lib/drawings/drag";

// Daily sessions, 31 Mar - 25 Apr 2025: Good Friday (18 Apr) is a NYSE holiday.
const DAILY = [
  "2025-03-27",
  "2025-03-28",
  "2025-03-31",
  "2025-04-01",
  "2025-04-02",
  "2025-04-03",
  "2025-04-04",
  "2025-04-07",
  "2025-04-14",
  "2025-04-15",
  "2025-04-16",
  "2025-04-17",
  "2025-04-21",
];
// The API's weekly bars carry the period's last stored session.
const WEEKLY = ["2025-03-28", "2025-04-04", "2025-04-11", "2025-04-17", "2025-04-25"];
const MONTHLY = ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"];

describe("periodKey", () => {
  it("uses ISO weeks and calendar months", () => {
    expect(periodKey("2025-04-17", "1wk")).toBe("2025-04-14");
    expect(periodKey("2025-04-20", "1wk")).toBe("2025-04-14"); // Sunday
    expect(periodKey("2025-04-21", "1wk")).toBe("2025-04-21");
    expect(periodKey("2025-04-01", "1wk")).toBe("2025-03-31"); // week spans a month
    expect(periodKey("2025-04-17", "1mo")).toBe("2025-04-01");
    expect(periodKey("2025-04-17", "1d")).toBe("2025-04-17");
  });
});

describe("anchorBarTime: daily ts -> bar time", () => {
  it("is the bar of that date on daily bars", () => {
    expect(anchorBarTime("2025-04-03", "1d", DAILY)).toBe("2025-04-03");
    expect(anchorBarTime("2025-04-05", "1d", DAILY)).toBeNull(); // a Saturday
  });

  it("is the week's bar on weekly bars, the Thursday in a holiday week", () => {
    expect(anchorBarTime("2025-04-14", "1wk", WEEKLY)).toBe("2025-04-17");
    expect(anchorBarTime("2025-04-17", "1wk", WEEKLY)).toBe("2025-04-17");
    // Monday 31 Mar and Tuesday 1 Apr are one ISO week, ending 4 Apr.
    expect(anchorBarTime("2025-03-31", "1wk", WEEKLY)).toBe("2025-04-04");
    expect(anchorBarTime("2025-04-01", "1wk", WEEKLY)).toBe("2025-04-04");
  });

  it("is the month's bar on monthly bars, across the month boundary", () => {
    expect(anchorBarTime("2025-03-31", "1mo", MONTHLY)).toBe("2025-03-31");
    expect(anchorBarTime("2025-04-01", "1mo", MONTHLY)).toBe("2025-04-30");
    expect(anchorBarTime("2024-12-31", "1mo", MONTHLY)).toBeNull();
  });
});

describe("anchorLogical", () => {
  it("is the bar index when a bar holds the date", () => {
    expect(anchorLogical("2025-04-15", "1wk", WEEKLY)).toBe(3);
    expect(anchorLogical("2025-04-04", "1d", DAILY)).toBe(6);
  });

  it("interpolates in time between bars", () => {
    // Saturday 5 Apr sits a third of the way from Fri 4 Apr (6) to Mon 7 Apr (7).
    expect(anchorLogical("2025-04-05", "1d", DAILY)).toBeCloseTo(6 + 1 / 3, 6);
  });

  it("extrapolates outside the loaded bars at the average spacing", () => {
    const bars = ["2025-04-07", "2025-04-08", "2025-04-09"];
    expect(anchorLogical("2025-04-06", "1d", bars)).toBeCloseTo(-1, 6);
    expect(anchorLogical("2025-04-11", "1d", bars)).toBeCloseTo(4, 6);
    expect(anchorLogical("2025-04-07", "1d", [])).toBeNull();
  });

  it("is the same in Tokyo and UTC (no local-time parsing)", () => {
    const before = process.env.TZ;
    process.env.TZ = "Asia/Tokyo";
    try {
      expect(anchorBarTime("2025-04-14", "1wk", WEEKLY)).toBe("2025-04-17");
      expect(periodKey("2025-04-20", "1wk")).toBe("2025-04-14");
    } finally {
      process.env.TZ = before;
    }
  });
});

describe("placing and dragging", () => {
  it("places the bar under the pointer, never past the last bar", () => {
    expect(logicalToDate(2.4, WEEKLY)).toBe("2025-04-11");
    expect(logicalToDate(99, WEEKLY)).toBe("2025-04-25");
    expect(logicalToDate(-3, WEEKLY)).toBe("2025-03-28");
    expect(placePoint("trendline", 0, { logical: 1, price: 101.234 }, WEEKLY)).toEqual({
      ts: "2025-04-04",
      price: "101.23",
    });
    // A position's stop is a price only; an hline too.
    expect(placePoint("position_long", 1, { logical: 1, price: 95 }, WEEKLY)).toEqual({
      ts: null,
      price: "95.00",
    });
    expect(placePoint("hline", 0, { logical: 1, price: 0.51234 }, WEEKLY)).toEqual({
      ts: null,
      price: "0.5123",
    });
    expect(roundPrice(-5)).toBe("0.01");
    expect(roundPrice(0.00001)).toBe("0.0001");
  });

  it("moves one handle, or the whole drawing by whole bars", () => {
    const points = [
      { ts: "2025-04-04", price: "100.00" },
      { ts: "2025-04-17", price: "110.00" },
    ];
    expect(
      dragPoints(
        "trendline",
        points,
        1,
        { logical: 3, price: 110 },
        { logical: 4.2, price: 112 },
        "1wk",
        WEEKLY,
      ),
    ).toEqual([points[0], { ts: "2025-04-25", price: "112.00" }]);
    expect(
      dragPoints(
        "trendline",
        points,
        null,
        { logical: 2, price: 105 },
        { logical: 1.1, price: 100 },
        "1wk",
        WEEKLY,
      ),
    ).toEqual([
      { ts: "2025-03-28", price: "95.00" },
      { ts: "2025-04-11", price: "105.00" },
    ]);
  });
});
