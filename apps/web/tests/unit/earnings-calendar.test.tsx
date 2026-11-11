import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EarningsCalendar, viewRange } from "@/components/earnings-calendar";
import type { EarningsEvent } from "@/lib/api/types";

const anchor = new Date("2026-08-05T12:00:00Z");

function event(overrides: Partial<EarningsEvent> = {}): EarningsEvent {
  return {
    id: 1,
    ticker: "AAPL",
    name: "Apple Inc.",
    event_date: "2026-08-05",
    report_time: "AMC",
    fiscal_period: null,
    eps_estimate: null,
    eps_actual: null,
    surprise_pct: null,
    result: "unknown",
    source: "fixture",
    fetched_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("EarningsCalendar", () => {
  it("keeps scheduled events honest when provider EPS is unavailable", () => {
    render(<EarningsCalendar events={[event()]} view="day" scope="all" anchor={anchor} />);

    expect(screen.getByRole("link", { name: /AAPL.*Apple Inc\./ })).toHaveAttribute(
      "href",
      "/stocks/AAPL",
    );
    expect(screen.getByText(/AMC/)).toBeVisible();
    expect(screen.queryByText(/Beat|Miss|In line/)).not.toBeInTheDocument();
  });

  it("shows a derived result and preserves shareable calendar state", () => {
    render(
      <EarningsCalendar
        events={[event({ eps_estimate: "1.00", eps_actual: "1.12", result: "beat" })]}
        view="day"
        scope="holdings"
        anchor={anchor}
      />,
    );

    expect(screen.getByText("Beat")).toBeVisible();
    expect(screen.getByRole("link", { name: "month" })).toHaveAttribute(
      "href",
      "/earnings?view=month&date=2026-08-05&scope=holdings",
    );
  });
});

describe("EarningsCalendar month grid", () => {
  it("starts weeks on Monday, rings today and dates each cell by its UTC day", () => {
    const { container } = render(
      <EarningsCalendar
        events={[
          event({
            event_date: "2026-08-03",
            eps_estimate: "1.00",
            eps_actual: "0.90",
            result: "miss",
          }),
        ]}
        view="month"
        scope="all"
        anchor={anchor}
        today="2026-08-05"
      />,
    );

    const grid = container.querySelector(".grid-cols-7");
    expect(grid?.textContent?.startsWith("MonTue")).toBe(true);
    // August 2026 starts on a Saturday: the first row runs Mon 27 Jul to Sun 2 Aug.
    const cells = container.querySelectorAll(".grid-cols-7 + .grid-cols-7 > div");
    expect(cells[0]?.textContent).toContain("27");
    expect(cells.length % 7).toBe(0);
    expect(container.querySelector('[aria-current="date"]')?.textContent).toBe("5");
    expect(screen.getAllByText("Miss").length).toBeGreaterThan(0);
  });
});

describe("viewRange", () => {
  it("runs a week from Monday to Sunday", () => {
    // 5 Aug 2026 is a Wednesday.
    expect(viewRange(anchor, "week")).toEqual({ from: "2026-08-03", to: "2026-08-09" });
  });

  it("covers the whole month", () => {
    expect(viewRange(anchor, "month")).toEqual({ from: "2026-08-01", to: "2026-08-31" });
  });
});
