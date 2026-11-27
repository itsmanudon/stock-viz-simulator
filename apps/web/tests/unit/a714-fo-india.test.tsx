// A7.14: India option summaries render figures, sparklines and the smile; empty locally unloaded.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FoIndiaView } from "@/components/fo-india-view";
import type { FoIndia } from "@/lib/api/fo";

const data: FoIndia = {
  underlyings: [
    {
      underlying: "NIFTY",
      series: "weekly",
      first: "2024-07-23",
      last: "2026-01-14",
      sessions: 2,
      iv_now: 9.49,
      iv_rank: 2.7,
      iv_percentile: 20.1,
      days: [
        { day: "2026-01-13", atm_iv: 10.1, skew: 1.5, pcr: 1.0, spot: 25800 },
        { day: "2026-01-14", atm_iv: 9.49, skew: 1.8, pcr: 1.11, spot: 25900 },
      ],
      smile: [
        { offset: -1, call_iv: 9.8, put_iv: 10.4 },
        { offset: 0, call_iv: 9.4, put_iv: 9.6 },
      ],
    },
  ],
  skew_offset: 2,
  min_days: 60,
  method: "ATM IV is the mean of the ATM call's and put's IV.",
  source_note: "From the owner's minute files, loaded into a local database only.",
};

describe("FoIndiaView", () => {
  it("shows figures, the smile and no gain or loss colours", () => {
    const { container } = render(<FoIndiaView data={data} />);
    const figures = screen.getAllByTestId("fo-figure").map((e) => e.textContent);
    expect(figures).toEqual(["9.49", "3", "20%", "1.80", "1.11"]);
    expect(screen.getByText("ATM-1")).toBeTruthy();
    expect(screen.getByText("ATM")).toBeTruthy();
    expect(container.querySelector(".text-positive, .text-negative")).toBeNull();
  });

  it("says when nothing is stored", () => {
    render(<FoIndiaView data={{ ...data, underlyings: [] }} />);
    expect(screen.getByTestId("fo-empty")).toBeTruthy();
  });
});
