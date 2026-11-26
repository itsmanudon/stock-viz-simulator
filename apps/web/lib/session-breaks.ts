/**
 * Session breaks on intraday charts (A6.2).
 *
 * Lightweight Charts places bars one after another by index, so nights,
 * weekends and holidays already take no room and no bar is invented across
 * them. What the eye loses is where one session ends and the next begins;
 * this primitive draws a faint dashed line between the last bar of a session
 * and the first bar of the next, and the time axis (with the venue-zone tick
 * formatter in `price-chart.tsx`) prints the new date there.
 */

import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";

/** Indices of the bars that open a new session (never the first bar). */
export function sessionStarts(sessionDates: readonly string[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < sessionDates.length; i++) {
    if (sessionDates[i] !== sessionDates[i - 1]) out.push(i);
  }
  return out;
}

type RenderTarget = Parameters<IPrimitivePaneRenderer["draw"]>[0];

class Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly xs: readonly number[],
    private readonly colour: string,
  ) {}
  draw(target: RenderTarget): void {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      context.strokeStyle = this.colour;
      context.lineWidth = 1;
      context.globalAlpha = 0.6;
      context.setLineDash([3, 4]);
      for (const x of this.xs) {
        const px = Math.round(x) + 0.5;
        context.beginPath();
        context.moveTo(px, 0);
        context.lineTo(px, mediaSize.height);
        context.stroke();
      }
      context.restore();
    });
  }
}

class View implements IPrimitivePaneView {
  constructor(private readonly host: SessionBreaksPrimitive) {}
  zOrder() {
    return "bottom" as const;
  }
  renderer(): IPrimitivePaneRenderer {
    return new Renderer(this.host.positions, this.host.colour);
  }
}

export class SessionBreaksPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApiBase<Time> | null = null;
  private readonly views = [new View(this)];
  /** Pixel x of each break as of the last update (the chart calls it on every change). */
  positions: number[] = [];

  constructor(
    private readonly starts: readonly number[],
    readonly colour: string,
  ) {}

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart;
    this.updateAllViews();
  }

  updateAllViews(): void {
    this.positions = this.xs();
  }

  detached(): void {
    this.chart = null;
  }

  /** Pixel x of each break: halfway between the session's last bar and the next one's first. */
  xs(): number[] {
    const scale = this.chart?.timeScale();
    if (!scale) return [];
    const out: number[] = [];
    for (const i of this.starts) {
      // Whole bars only: 5.3 maps a fractional logical index to 0.
      const before = scale.logicalToCoordinate((i - 1) as Logical);
      const after = scale.logicalToCoordinate(i as Logical);
      if (before !== null && after !== null) out.push((before + after) / 2);
    }
    return out;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }
}
