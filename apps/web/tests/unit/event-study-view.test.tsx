import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventStudyView, NewsReactions } from "@/components/event-study-view";
import type { EventStudy } from "@/lib/api/research";

const base: EventStudy = {
  tickers: ["AAPL"],
  sentiment: "negative",
  event_type: null,
  pre: 5,
  post: 20,
  model: "market-adjusted: stock log return minus its market index's",
  benchmarks: { AAPL: "^GSPC" },
  no_benchmark: [],
  min_events: 10,
  enough: true,
  events_found: 14,
  events_used: 12,
  events_incomplete: 2,
  overlapping: 0,
  windows: [
    { start: 0, end: 1, mean_car_pct: -1.234, std_error_pct: 0.4, t_stat: -3.09 },
    { start: -5, end: -1, mean_car_pct: 0.1, std_error_pct: 0.2, t_stat: 0.5 },
  ],
  path: [
    { offset: -1, mean_car_pct: 0, std_error_pct: 0 },
    { offset: 0, mean_car_pct: -1, std_error_pct: 0.3 },
    { offset: 1, mean_car_pct: -1.2, std_error_pct: 0.4 },
  ],
  events: [
    {
      ticker: "AAPL",
      document_id: "d1",
      title: "Apple misses",
      available_at: "2026-11-10T21:00:00",
      event_date: "2026-11-11",
      car_pct: -2.5,
    },
  ],
};

describe("EventStudyView (Phase 7.4)", () => {
  it("states the method, counts and windows", () => {
    render(<EventStudyView study={base} />);
    expect(screen.getByText(/12 of 14 news items used; 2 lacked a full window/)).toBeVisible();
    expect(screen.getByText("day 0 to +1")).toBeVisible();
    expect(screen.getByText("−1.23%")).toBeVisible();
    expect(screen.getByText("-5 to -1")).toBeVisible();
    expect(screen.getByRole("img", { name: /Mean cumulative abnormal return/ })).toBeVisible();
    expect(screen.getByText(/not a cause/)).toBeVisible();
  });

  it("shows counts but no figures below the minimum", () => {
    render(<EventStudyView study={{ ...base, enough: false, windows: [], path: [] }} />);
    expect(screen.getByTestId("too-few-events")).toHaveTextContent("Fewer than 10");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("links the stock page block to the full study", () => {
    render(<NewsReactions ticker="INFY.NS" negative={base} positive={null} />);
    expect(screen.getByRole("link", { name: "Open the full study" })).toHaveAttribute(
      "href",
      "/news-reactions?tickers=INFY.NS",
    );
    expect(screen.getByText("After negative news")).toBeVisible();
  });
});
