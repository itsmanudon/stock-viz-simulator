import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RangeBar, rangePositionPct } from "@/components/range-bar";
import { StrengthDots } from "@/components/strength-dots";
import { seriesDash } from "@/lib/compare-workspace";

describe("rangePositionPct", () => {
  it("places a value between the low and the high", () => {
    expect(rangePositionPct(150, 100, 200)).toBe(50);
    expect(rangePositionPct(100, 100, 200)).toBe(0);
  });

  it("returns null for missing, malformed or flat ranges", () => {
    expect(rangePositionPct(null, 100, 200)).toBeNull();
    expect(rangePositionPct(Number.NaN, 100, 200)).toBeNull();
    expect(rangePositionPct(150, 200, 200)).toBeNull();
  });
});

describe("RangeBar", () => {
  it("names the position for assistive tech and clamps the marker", () => {
    const { container } = render(
      <RangeBar positionPct={140} low="$100.00" high="$200.00" label="Above the range" />,
    );
    expect(screen.getByRole("img", { name: "Above the range" })).toBeInTheDocument();
    expect(container.querySelector('[style*="left"]')).toHaveStyle({ left: "100%" });
  });

  it("shows a dash without a position", () => {
    render(<RangeBar positionPct={null} label="Unavailable" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("StrengthDots", () => {
  it("fills one dot per supporting vote and prints the count", () => {
    const { container } = render(<StrengthDots score={4} max={7} />);
    expect(screen.getByText("4/7")).toBeVisible();
    expect(container.querySelectorAll(".bg-foreground")).toHaveLength(4);
  });
});

describe("seriesDash", () => {
  it("gives neighbouring compare series different line styles", () => {
    expect([0, 1, 2, 3].map(seriesDash)).toEqual(["solid", "dashed", "dotted", "solid"]);
  });
});
