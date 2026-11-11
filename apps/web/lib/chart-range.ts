import type { IChartApi } from "lightweight-charts";

/**
 * Half the width of the widest time-axis label ("2025", "Sep 17"), plus a
 * little air. lightweight-charts centres each label on its tick and clips at
 * the plot edge, so a tick within this distance of an edge lost its first or
 * last letters ("ug", "25"; UI audit P4).
 */
export const AXIS_LABEL_ROOM_PX = 24;

/**
 * Like `timeScale().fitContent()`, but leaves `AXIS_LABEL_ROOM_PX` of empty
 * time at both ends. Ticks only sit on real bars, so no label can then start
 * or end outside the plot.
 *
 * `fallbackWidth` covers the first paint under `autoSize`, before the time
 * scale has measured itself.
 */
export function fitWithLabelRoom(chart: IChartApi, barCount: number, fallbackWidth: number): void {
  const timeScale = chart.timeScale();
  if (barCount < 2) {
    timeScale.fitContent();
    return;
  }
  const width = timeScale.width() || fallbackWidth;
  if (width <= AXIS_LABEL_ROOM_PX * 4) {
    timeScale.fitContent();
    return;
  }
  // The visible span is (barCount - 1 + 2 * pad) bars across `width` px, and
  // the outer bars must sit `room` px in: solve
  // pad = room * (barCount - 1 + 2 * pad) / width for pad.
  const pad = (AXIS_LABEL_ROOM_PX * (barCount - 1)) / (width - 2 * AXIS_LABEL_ROOM_PX);
  timeScale.setVisibleLogicalRange({ from: -pad, to: barCount - 1 + pad });
}
