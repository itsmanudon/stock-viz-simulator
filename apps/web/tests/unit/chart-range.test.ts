import type { IChartApi } from "lightweight-charts";
import { describe, expect, it, vi } from "vitest";

import { AXIS_LABEL_ROOM_PX, fitWithLabelRoom } from "@/lib/chart-range";

function fakeChart(width: number) {
  const timeScale = {
    width: vi.fn(() => width),
    fitContent: vi.fn(),
    setVisibleLogicalRange: vi.fn(),
  };
  return { chart: { timeScale: () => timeScale } as unknown as IChartApi, timeScale };
}

describe("fitWithLabelRoom (UI audit P4)", () => {
  it("leaves room for a centred label at both ends", () => {
    const { chart, timeScale } = fakeChart(300);
    fitWithLabelRoom(chart, 63, 0);
    const { from, to } = timeScale.setVisibleLogicalRange.mock.calls[0][0];
    // The first and last bars sit AXIS_LABEL_ROOM_PX in from each edge.
    const pxPerBar = 300 / (to - from);
    expect(-from * pxPerBar).toBeCloseTo(AXIS_LABEL_ROOM_PX, 5);
    expect((to - 62) * pxPerBar).toBeCloseTo(AXIS_LABEL_ROOM_PX, 5);
  });

  it("uses the fallback width before the chart has measured itself", () => {
    const { chart, timeScale } = fakeChart(0);
    fitWithLabelRoom(chart, 100, 400);
    expect(timeScale.setVisibleLogicalRange).toHaveBeenCalled();
  });

  it("falls back to a plain fit when there is too little to pad", () => {
    for (const [width, bars] of [
      [300, 1],
      [60, 50],
      [0, 50],
    ] as const) {
      const { chart, timeScale } = fakeChart(width);
      fitWithLabelRoom(chart, bars, 0);
      expect(timeScale.fitContent).toHaveBeenCalled();
      expect(timeScale.setVisibleLogicalRange).not.toHaveBeenCalled();
    }
  });
});
