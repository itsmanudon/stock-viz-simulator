/**
 * The primitive host (A3.2): one Lightweight Charts series primitive,
 * attached to the price series, that draws every drawing on the price pane.
 *
 * Geometry, hit-testing and painting live in `scene.ts`; this class only
 * keeps the state, asks the chart for coordinates and hands the shapes to the
 * renderer. Horizontal lines also get a label on the price scale.
 */

import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  Logical,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

import type { ChartPalette } from "@/lib/chart-theme";
import type { StockInterval } from "@/lib/stock-workspace";

import {
  type PaintContext,
  type SceneContext,
  type SceneDrawing,
  type Shape,
  buildScene,
  hitScene,
  paintScene,
} from "./scene";

type RenderTarget = Parameters<IPrimitivePaneRenderer["draw"]>[0];

export type DrawingsState = {
  drawings: readonly SceneDrawing[];
  selectedId: string | null;
  interval: StockInterval;
  barDates: readonly string[];
  palette: ChartPalette;
  fontFamily: string;
};

class Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly shapes: readonly Shape[],
    private readonly font: string,
  ) {}
  draw(target: RenderTarget): void {
    target.useMediaCoordinateSpace(({ context }) => {
      paintScene(context as unknown as PaintContext, this.shapes, this.font);
    });
  }
}

class PaneView implements IPrimitivePaneView {
  constructor(private readonly host: DrawingsPrimitive) {}
  zOrder() {
    return "top" as const;
  }
  renderer(): IPrimitivePaneRenderer {
    return new Renderer(this.host.shapes, this.host.state?.fontFamily ?? "sans-serif");
  }
}

class PriceLabel implements ISeriesPrimitiveAxisView {
  constructor(
    private readonly y: number,
    private readonly label: string,
    private readonly back: string,
    private readonly fore: string,
  ) {}
  coordinate() {
    return this.y;
  }
  text() {
    return this.label;
  }
  textColor() {
    return this.fore;
  }
  backColor() {
    return this.back;
  }
}

export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  state: DrawingsState | null = null;
  shapes: Shape[] = [];
  private chart: IChartApiBase<Time> | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly views: IPrimitivePaneView[] = [new PaneView(this)];
  private axisViews: ISeriesPrimitiveAxisView[] = [];

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

  setState(state: DrawingsState): void {
    this.state = state;
    this.updateAllViews();
    this.requestUpdate?.();
  }

  /** The scene context for the chart as it is now, or null before attaching. */
  context(): SceneContext | null {
    const chart = this.chart;
    const series = this.series;
    const state = this.state;
    if (!chart || !series || !state) return null;
    const timeScale = chart.timeScale();
    const pane = chart.panes()[0];
    return {
      interval: state.interval,
      barDates: state.barDates,
      // 5.3 maps a fractional logical index to 0, so interpolate between
      // the whole bars around it (an anchor dated between two bars, A6.2 find).
      xOfLogical: (logical) => {
        const lo = Math.floor(logical);
        const a = timeScale.logicalToCoordinate(lo as Logical);
        if (logical === lo || a === null) return a;
        const b = timeScale.logicalToCoordinate((lo + 1) as Logical);
        return b === null ? null : a + (b - a) * (logical - lo);
      },
      yOfPrice: (price) => series.priceToCoordinate(price),
      width: timeScale.width(),
      height: pane?.getHeight() ?? 0,
      colours: {
        drawing: state.palette.drawing,
        positive: state.palette.positive,
        negative: state.palette.negative,
        text: state.palette.text,
        labelBg: state.palette.labelBg,
      },
    };
  }

  updateAllViews(): void {
    const ctx = this.context();
    const state = this.state;
    if (!ctx || !state) {
      this.shapes = [];
      this.axisViews = [];
      return;
    }
    this.shapes = buildScene(state.drawings, ctx, state.selectedId);
    this.axisViews = state.drawings
      .filter((d) => d.kind === "hline" && d.points[0])
      .flatMap((d) => {
        const y = ctx.yOfPrice(Number(d.points[0].price));
        if (y === null) return [];
        const colour = ctx.colours.drawing[d.style.colour] ?? ctx.colours.drawing.aqua;
        return [
          new PriceLabel(y, Number(d.points[0].price).toFixed(2), colour, ctx.colours.labelBg),
        ];
      });
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    return this.axisViews;
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const hit = hitScene(this.shapes, x, y);
    if (!hit) return null;
    const locked = this.state?.drawings.find((d) => d.id === hit.id)?.locked;
    return {
      externalId: `drawing:${hit.id}`,
      zOrder: "top",
      distance: hit.distance,
      hitTestPriority: hit.handle === null ? 1 : 2,
      cursorStyle: locked ? "default" : hit.handle === null ? "move" : "grab",
    };
  }

  /** Pane pixels -> a logical index and a price, for placing and dragging. */
  toChart(x: number, y: number): { logical: number; price: number } | null {
    const chart = this.chart;
    const series = this.series;
    if (!chart || !series) return null;
    const logical = chart.timeScale().coordinateToLogical(x);
    const price = series.coordinateToPrice(y);
    if (logical === null || price === null) return null;
    return { logical, price };
  }
}
