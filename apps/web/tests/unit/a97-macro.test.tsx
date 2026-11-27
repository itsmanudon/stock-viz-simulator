// A9.7: the macro board shows each series' value, changes in the right unit,
// stale and unfetched states, spreads and their reasons, all in neutral colours.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MacroView, formatMacroChange, formatMacroValue, macroDate } from "@/components/macro-view";
import type { MacroOverview } from "@/lib/api/macro";

const spark = [
  { day: "2025-11-24", value: 4.0 },
  { day: "2026-11-24", value: 4.91 },
];

const overview: MacroOverview = {
  groups: ["Rates", "Inflation", "India"],
  series: [
    {
      series_id: "DGS10",
      group: "Rates",
      label: "US Treasury 10-year yield",
      title: "Market Yield on U.S. Treasury Securities at 10-Year",
      units: "Percent",
      frequency: "Daily",
      third_party: false,
      fetched: true,
      fetched_at: "2026-11-27T02:00:00",
      latest: { day: "2026-11-24", value: 4.91 },
      change_month: 0.12,
      change_year: 0.87,
      stale: false,
      spark,
      source_url: "https://fred.stlouisfed.org/series/DGS10",
    },
    {
      series_id: "CPIAUCSL",
      group: "Inflation",
      label: "US CPI, all items",
      units: "Index 1982-1984=100",
      frequency: "Monthly",
      third_party: false,
      fetched: true,
      latest: { day: "2026-10-01", value: 337.476 },
      change_month: 1,
      change_year: 13.231,
      stale: true,
      spark,
      source_url: "https://fred.stlouisfed.org/series/CPIAUCSL",
    },
    {
      series_id: "INDIRLTLT01STM",
      group: "India",
      label: "India 10-year government bond yield (OECD)",
      third_party: false,
      fetched: false,
      stale: true,
      spark: [],
      source_url: "https://fred.stlouisfed.org/series/INDIRLTLT01STM",
    },
  ],
  spreads: [
    {
      key: "us_10y_2y",
      label: "10-year minus 2-year",
      a: "DGS10",
      b: "DGS2",
      units: "percentage points",
      note: "Below zero, the curve is inverted.",
      latest: { day: "2026-11-24", value: 0.28 },
      year_ago: { day: "2025-11-24", value: -0.02 },
      points: spark,
    },
    {
      key: "brent_wti",
      label: "Brent minus WTI",
      a: "DCOILBRENTEU",
      b: "DCOILWTICO",
      units: "dollars a barrel",
      note: "Seaborne vs inland.",
      points: [],
      reason: "No stored values for DCOILBRENTEU.",
    },
  ],
  last_fetched_at: "2026-11-27T02:00:00",
  source: "FRED, Federal Reserve Bank of St. Louis",
  third_party_note: "Third-party series need a licence check.",
  method: "Values as FRED publishes them.",
};

describe("macro formatting", () => {
  it("formats dates, values and changes by unit", () => {
    expect(macroDate("2026-11-24")).toBe("Nov 24, 2026");
    expect(formatMacroValue(4.91, "Percent")).toBe("4.91%");
    expect(formatMacroValue(159293, "Thousands of Persons")).toBe("159,293");
    expect(formatMacroChange(0.87, 4.91, "Percent")).toBe("+0.87 pts");
    expect(formatMacroChange(-0.3, 4.1, "Percent")).toBe("−0.30 pts");
    // 13.231 on a level of 337.476: 4.1% over the year's starting level.
    expect(formatMacroChange(13.231, 337.476, "Index 1982-1984=100")).toBe("+4.1%");
    expect(formatMacroChange(null, 4.9, "Percent")).toBe("—");
  });
});

describe("MacroView", () => {
  it("renders series, stale and unfetched states and spreads", () => {
    render(<MacroView overview={overview} />);
    const ten = screen.getAllByTestId("macro-series").find((el) => el.dataset.series === "DGS10");
    expect(ten).toBeDefined();
    const t = within(ten as HTMLElement);
    expect(t.getByTestId("macro-value").textContent).toBe("4.91%");
    expect(t.getByText("+0.87 pts")).toBeTruthy();
    const cpi = screen
      .getAllByTestId("macro-series")
      .find((el) => el.dataset.series === "CPIAUCSL") as HTMLElement;
    expect(cpi.dataset.stale).toBe("true");
    expect(within(cpi).getByText(/Not Updated Recently/)).toBeTruthy();
    expect(screen.getByText("Not fetched yet.")).toBeTruthy();
    const spreads = screen.getAllByTestId("macro-spread");
    expect(within(spreads[0]).getByTestId("macro-spread-now").textContent).toBe(
      "0.28 pts (Nov 24, 2026)",
    );
    expect(within(spreads[1]).getByText("No stored values for DCOILBRENTEU.")).toBeTruthy();
    expect(screen.queryByTestId("macro-empty")).toBeNull();
  });

  it("never colours a series as a gain or a loss", () => {
    const { container } = render(<MacroView overview={overview} />);
    expect(container.querySelector(".text-positive, .text-negative")).toBeNull();
  });

  it("says when nothing is stored", () => {
    render(
      <MacroView
        overview={{ ...overview, series: overview.series.map((s) => ({ ...s, fetched: false })) }}
      />,
    );
    expect(screen.getByTestId("macro-empty")).toBeTruthy();
  });
});
