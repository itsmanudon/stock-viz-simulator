import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "@/components/sparkline";

function svgOf(ui: React.ReactElement) {
  const { container } = render(ui);
  return container.querySelector("svg") as SVGSVGElement;
}

describe("Sparkline", () => {
  it("renders a placeholder rather than a broken path for thin data", () => {
    const svg = svgOf(<Sparkline closes={[100]} />);
    expect(svg).toHaveAttribute("aria-label", "no data");
    expect(svg.querySelector("path")).toBeNull();
  });

  it("draws a dashed baseline by default", () => {
    const svg = svgOf(<Sparkline closes={[100, 110, 105]} />);
    const baseline = svg.querySelector("line");

    expect(baseline).not.toBeNull();
    expect(baseline).toHaveAttribute("stroke-dasharray", "3 3");
  });

  it("omits the baseline when asked", () => {
    const svg = svgOf(<Sparkline closes={[100, 110]} showBaseline={false} />);
    expect(svg.querySelector("line")).toBeNull();
  });

  it("colours by the close relative to the baseline, not the series minimum", () => {
    // Ends below where it started, despite rallying in between.
    const down = svgOf(<Sparkline closes={[100, 130, 95]} />);
    expect(down.getAttribute("class")).toContain("text-negative");

    const up = svgOf(<Sparkline closes={[100, 80, 115]} />);
    expect(up.getAttribute("class")).toContain("text-positive");
  });

  it("honours an explicit baseline over the first close", () => {
    // Series only rises, but against a higher reference it is still down.
    const svg = svgOf(<Sparkline closes={[100, 105, 110]} baseline={200} />);
    expect(svg.getAttribute("class")).toContain("text-negative");
  });

  it("keeps the baseline inside the drawn area when the series moved away from it", () => {
    const svg = svgOf(<Sparkline closes={[100, 101, 102]} baseline={50} height={28} />);
    const y = Number(svg.querySelector("line")?.getAttribute("y1"));

    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThanOrEqual(28);
  });

  it("describes the direction for assistive tech", () => {
    const svg = svgOf(<Sparkline closes={[100, 120]} periodLabel="90-day" />);
    expect(svg).toHaveAttribute("aria-label", expect.stringContaining("90-day"));
    expect(svg.getAttribute("aria-label")).toContain("up");
  });
});
