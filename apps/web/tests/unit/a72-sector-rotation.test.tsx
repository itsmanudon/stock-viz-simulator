// A7.2: the sector rotation map draws each sector's trail and names the quadrants.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectorRotationMap, rotationSpan } from "@/components/sector-rotation-map";
import type { Rotation } from "@/lib/api/sector-rotation";

const rotation: Rotation = {
  market: "US",
  benchmark: "^GSPC",
  benchmark_name: "S&P 500",
  as_of: "2026-11-27",
  note: "Equal-weight composites of today's members. Not RRG®.",
  method: {},
  sectors: [
    {
      sector: "Technology",
      members: 5,
      points: [
        { week: "2026-11-20", rs_trend: 101, rs_momentum: 102, quadrant: "leading" },
        { week: "2026-11-27", rs_trend: 103.5, rs_momentum: 101, quadrant: "leading" },
      ],
    },
    {
      sector: "Energy",
      members: 4,
      points: [{ week: "2026-11-27", rs_trend: 96, rs_momentum: 99, quadrant: "lagging" }],
    },
  ],
};

describe("SectorRotationMap", () => {
  it("labels sectors and quadrants", () => {
    render(<SectorRotationMap rotation={rotation} />);
    const map = screen.getByTestId("rotation-US");
    for (const label of ["Technology", "Energy", "Leading", "Lagging", "Improving", "Weakening"]) {
      expect(map).toHaveTextContent(label);
    }
    expect(map).toHaveTextContent("Against S&P 500");
  });

  it("scales to the furthest point", () => {
    expect(rotationSpan(rotation)).toBe(5); // 4 from Energy's trend, x 1.1, rounded up
  });

  it("says when there is not enough history", () => {
    render(<SectorRotationMap rotation={{ ...rotation, sectors: [] }} />);
    expect(screen.getByText(/Not enough sector history/)).toBeVisible();
  });
});
