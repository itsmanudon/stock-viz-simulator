/**
 * Volume profile primitive (A6.7, M2.9): one Lightweight Charts series
 * primitive on the price pane that draws every profile shown, after
 * TradingView's Volume Profile plugin example (it has no npm package).
 *
 * - The visible-range profile grows leftwards from the pane's right edge.
 * - A fixed-range profile grows rightwards from its first session, at most
 *   the width between its two sessions.
 *
 * Bins inside the value area are drawn stronger, the POC is a solid line and
 * VAH/VAL dashed ones. The geometry is `lib/volume-profile.ts::profileGeometry`;
 * this class keeps the layers and asks the chart for coordinates.
 */

import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

import { type ProfileGeometry, type VolumeProfile, profileGeometry } from "@/lib/volume-profile";

type RenderTarget = Parameters<IPrimitivePaneRenderer["draw"]>[0];

export type ProfileLayer = {
  key: string;
  profile: VolumeProfile;
  /** `right`: the visible range, from the pane's right edge; `span`: between two bars. */
  placement: { kind: "right" } | { kind: "span"; from: number; to: number };
};

export type ProfileColours = { bins: string; value: string; poc: string; levels: string };

/** The share of the pane a visible-range profile may take. */
export const VISIBLE_WIDTH_SHARE = 0.25;
const MIN_SPAN_PX = 24;

type Paint = {
  fillStyle: string;
  strokeStyle: string;
  globalAlpha: number;
  lineWidth: number;
  fillRect: (x: number, y: number, w: number, h: number) => void;
  beginPath: () => void;
  moveTo: (x: number, y: number) => void;
  lineTo: (x: number, y: number) => void;
  stroke: () => void;
  setLineDash: (segments: number[]) => void;
  save: () => void;
  restore: () => void;
};

/** Paint the layers' geometry on a 2D context (pure apart from the context's calls). */
export function paintProfiles(
  context: Paint,
  shapes: readonly ProfileGeometry[],
  colours: ProfileColours,
): void {
  for (const g of shapes) {
    context.save();
    for (const r of g.rects) {
      context.globalAlpha = r.inValueArea ? 0.45 : 0.22;
      context.fillStyle = r.poc ? colours.poc : r.inValueArea ? colours.value : colours.bins;
      context.fillRect(r.x, r.y, r.width, r.height);
    }
    context.globalAlpha = 0.9;
    context.lineWidth = 1;
    const level = (y: number | null, colour: string, dash: number[]) => {
      if (y === null) return;
      context.strokeStyle = colour;
      context.setLineDash(dash);
      context.beginPath();
      context.moveTo(g.left, y);
      context.lineTo(g.right, y);
      context.stroke();
    };
    level(g.pocY, colours.poc, []);
    level(g.vahY, colours.levels, [4, 3]);
    level(g.valY, colours.levels, [4, 3]);
    context.restore();
  }
}

class Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly shapes: readonly ProfileGeometry[],
    private readonly colours: ProfileColours,
  ) {}
  draw(target: RenderTarget): void {
    target.useMediaCoordinateSpace(({ context }) => {
      paintProfiles(context as unknown as Paint, this.shapes, this.colours);
    });
  }
}

class PaneView implements IPrimitivePaneView {
  constructor(private readonly host: VolumeProfilePrimitive) {}
  zOrder() {
    // Under the candles: the profile is context, not a drawing.
    return "bottom" as const;
  }
  renderer(): IPrimitivePaneRenderer {
    return new Renderer(this.host.shapes, this.host.colours);
  }
}

export class VolumeProfilePrimitive implements ISeriesPrimitive<Time> {
  layers: ProfileLayer[] = [];
  shapes: ProfileGeometry[] = [];
  private chart: IChartApiBase<Time> | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly views: IPrimitivePaneView[] = [new PaneView(this)];

  /**
   * `source`, when given, is asked for the layers before every paint, so a
   * fixed range drawn a moment ago shows without a pan (the chart repaints
   * when the drawings change).
   */
  constructor(
    public colours: ProfileColours,
    private readonly source?: () => ProfileLayer[],
  ) {}

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
    this.updateAllViews();
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  setLayers(layers: ProfileLayer[], colours?: ProfileColours): void {
    this.layers = layers;
    if (colours) this.colours = colours;
    this.updateAllViews();
    this.requestUpdate?.();
  }

  updateAllViews(): void {
    if (this.source) this.layers = this.source();
    const chart = this.chart;
    const series = this.series;
    if (!chart || !series) {
      this.shapes = [];
      return;
    }
    const scale = chart.timeScale();
    const width = scale.width();
    const yOf = (price: number) => series.priceToCoordinate(price);
    const xOf = (logical: number) => scale.logicalToCoordinate(Math.round(logical) as Logical);
    const shapes: ProfileGeometry[] = [];
    for (const layer of this.layers) {
      if (layer.placement.kind === "right") {
        shapes.push(
          profileGeometry(layer.profile, yOf, {
            anchor: width,
            side: "left",
            maxWidth: width * VISIBLE_WIDTH_SHARE,
          }),
        );
        continue;
      }
      const a = xOf(layer.placement.from);
      const b = xOf(layer.placement.to);
      if (a === null || b === null) continue;
      const left = Math.min(a, b);
      const span = Math.max(MIN_SPAN_PX, Math.abs(b - a));
      shapes.push(
        profileGeometry(layer.profile, yOf, { anchor: left, side: "right", maxWidth: span * 0.7 }),
      );
    }
    this.shapes = shapes;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }
}
