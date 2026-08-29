import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EarningsCalendar } from "@/components/earnings-calendar";
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
