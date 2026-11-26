// A9.2: the forecast card shows skill against a random walk and realised coverage.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ForecastCard } from "@/components/forecast-card";
import type { Forecast } from "@/lib/api/research-views";

const forecast: Forecast = {
  ticker: "ACME",
  last_date: "2026-11-26",
  last_close: 100,
  volatility: {
    test_days: 250,
    har_mse: 1,
    rw_mse: 1.2,
    har_qlike: 0.1,
    rw_qlike: 0.13,
    skill_mse: 0.167,
    skill_qlike: -0.05,
    next_day_vol: 0.243,
    coefficients: [0, 0.3, 0.4, 0.2],
    reason: null,
  },
  cones: [
    { horizon: 1, level: 0.8, lower: 98.7, upper: 101.3, realised_coverage: 0.79, test_days: 250 },
    { horizon: 20, level: 0.95, lower: 85, upper: 117, realised_coverage: 0.84, test_days: 230 },
  ],
  cones_reason: null,
  method: { scoring: "Out of sample", honesty: "Not a price target", har: "", cones: "" },
};

describe("ForecastCard", () => {
  it("reports skill and coverage", () => {
    render(<ForecastCard forecast={forecast} />);
    expect(screen.getByTestId("forecast-vol")).toHaveTextContent("24.3%");
    expect(screen.getByText("+16.7%")).toBeVisible();
    expect(screen.getByText("-5.0%")).toBeVisible();
    const cones = screen.getByTestId("forecast-cones");
    expect(cones).toHaveTextContent("98.70 – 101.30");
    expect(cones).toHaveTextContent("84.0%");
    expect(screen.getByText("84.0%")).toHaveClass("text-warning"); // under its 95% level
  });
});
