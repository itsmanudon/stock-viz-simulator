// A9.1: the seasonality and earnings drift view.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeasonalityView } from "@/components/seasonality-view";
import type { EarningsDrift, Seasonality } from "@/lib/api/research-views";

const cell = (key: string, mean: number, n = 12) => ({
  key,
  n,
  mean,
  median: mean,
  hit_rate: 0.6,
  t_stat: 1.2,
  thin: n < 10,
});

const season: Seasonality = {
  ticker: "ACME",
  first: "2015-01-30",
  last: "2026-11-26",
  months: [cell("Jan", 2.1), cell("Feb", -1.3, 8)],
  weekdays: [cell("Mon", 0.05)],
  note: "Association, not a forecast.",
};

const drift: EarningsDrift = {
  ticker: "ACME",
  avg_abs_reaction: 4.2,
  avg_abs_day: 1.1,
  events: [
    {
      event_date: "2026-01-28",
      reaction_date: "2026-01-29",
      assumed: false,
      surprise_pct: 3,
      reaction: 5.1,
      d1: 0.4,
      d5: 1.2,
      d20: 2.0,
    },
  ],
  groups: [
    {
      group: "beat",
      horizons: [{ sessions: 1, n: 1, mean: 0.4, median: 0.4, hit_rate: 1, t_stat: null }],
    },
  ],
  note: "Reaction session rules.",
};

describe("SeasonalityView", () => {
  it("shows the month cells and the drift", () => {
    render(<SeasonalityView seasonality={season} drift={drift} />);
    expect(screen.getByTestId("seasonality")).toHaveTextContent("+2.1%");
    expect(screen.getByTestId("drift-summary")).toHaveTextContent("+4.20%");
    expect(screen.getByTestId("earnings-drift")).toHaveTextContent("Beat");
    expect(screen.getByText(/not a forecast/)).toBeVisible();
  });
});
