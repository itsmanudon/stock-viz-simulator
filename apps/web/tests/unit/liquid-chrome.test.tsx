import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StockVizMark, StockVizWordmark } from "@/components/brand/stockviz-mark";
import { LiquidChrome, moodAmount } from "@/components/prism/liquid-chrome";
import { LIQUID_CHROME_FRAGMENT } from "@/components/prism/liquid-chrome.glsl";

describe("Liquid Chrome breadth tint", () => {
  it("is neutral without a figure or at an even split", () => {
    expect(moodAmount(null)).toBe(0);
    expect(moodAmount(undefined)).toBe(0);
    expect(moodAmount(Number.NaN)).toBe(0);
    expect(moodAmount(0.5)).toBe(0);
  });

  it("grows with the lean either way and never passes 0.35", () => {
    expect(moodAmount(0.6)).toBeCloseTo(0.09);
    expect(moodAmount(0.4)).toBeCloseTo(0.09);
    expect(moodAmount(0.9)).toBe(0.35);
    expect(moodAmount(0)).toBe(0.35);
  });

  it("reads the brand and mood colours the component sets", () => {
    for (const name of ["uSteel", "uSilver", "uChampagne", "uMood", "uMoodAmount", "uPointer"]) {
      expect(LIQUID_CHROME_FRAGMENT).toMatch(new RegExp(`uniform \\w+ ${name};`));
    }
  });

  it("renders a decorative host that ignores the pointer", () => {
    const { container } = render(<LiquidChrome share={0.7} />);
    const host = container.firstElementChild as HTMLElement;
    expect(host.getAttribute("aria-hidden")).toBe("true");
    expect(host.className).toContain("pointer-events-none");
  });
});

describe("StockViz mark", () => {
  it("is decorative; the wordmark carries the name", () => {
    const { container } = render(<StockVizWordmark />);
    expect(container.textContent).toBe("StockViz");
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
  });

  it("gives each instance its own gradient ids", () => {
    const { container } = render(
      <>
        <StockVizMark />
        <StockVizMark />
      </>,
    );
    const ids = [...container.querySelectorAll("linearGradient")].map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
