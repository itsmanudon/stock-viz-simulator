import { describe, expect, it, vi } from "vitest";

import {
  EMPTY_HISTORY,
  inverse,
  record,
  remapId,
  takeRedo,
  takeUndo,
} from "@/lib/drawings/history";
import { DEFAULT_STYLE, type DrawingKind, type DrawingPoint } from "@/lib/drawings/kinds";
import { fibExtension, fibRetracement, positionStats, rulerStats } from "@/lib/drawings/math";
import { DrawingsPrimitive } from "@/lib/drawings/primitive";
import {
  type PaintContext,
  type SceneContext,
  type Shape,
  buildScene,
  drawingShapes,
  hitScene,
  paintScene,
  rayEnd,
} from "@/lib/drawings/scene";

const BARS = ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04", "2025-04-07"];

const COLOURS = {
  drawing: {
    aqua: "aqua",
    blue: "blue",
    violet: "violet",
    pink: "pink",
    amber: "amber",
    lime: "lime",
    slate: "slate",
    foreground: "white",
  },
  positive: "green",
  negative: "red",
  text: "grey",
  labelBg: "card",
};

// Ten pixels a bar; y = 200 - price.
const ctx: SceneContext = {
  interval: "1d",
  barDates: BARS,
  xOfLogical: (l) => l * 10,
  yOfPrice: (p) => 200 - p,
  width: 300,
  height: 200,
  colours: COLOURS,
};

function shapes(kind: DrawingKind, points: DrawingPoint[], label: string | null = null): Shape[] {
  return drawingShapes({ id: "1", kind, points, style: DEFAULT_STYLE, label }, ctx, false);
}

const lines = (s: Shape[]) => s.filter((x) => x.type === "line");
const texts = (s: Shape[]) => s.flatMap((x) => (x.type === "text" ? [x.text] : []));

describe("drawing math", () => {
  it("places Fibonacci retracement levels from the swing's end", () => {
    const levels = fibRetracement(100, 200);
    expect(levels.map((l) => l.label)).toEqual([
      "0%",
      "23.6%",
      "38.2%",
      "50%",
      "61.8%",
      "78.6%",
      "100%",
    ]);
    expect(levels.map((l) => Number(l.price.toFixed(1)))).toEqual([
      200, 176.4, 161.8, 150, 138.2, 121.4, 100,
    ]);
  });

  it("projects extensions from the retracement point", () => {
    const levels = fibExtension(100, 150, 120);
    expect(levels.map((l) => l.label)).toEqual([
      "0%",
      "61.8%",
      "100%",
      "127.2%",
      "161.8%",
      "261.8%",
    ]);
    expect(levels.find((l) => l.ratio === 1.618)?.price).toBeCloseTo(200.9, 6);
  });

  it("measures price, percent, bars and days", () => {
    expect(
      rulerStats(
        { date: "2025-04-01", price: 100, logical: 0 },
        { date: "2025-04-07", price: 110, logical: 4 },
      ),
    ).toEqual({ deltaPrice: 10, deltaPct: 10, bars: 4, days: 6 });
  });

  it("works out the position tool's R", () => {
    expect(positionStats("long", 100, 95, 115)).toEqual({
      side: "long",
      riskPerShare: 5,
      rewardPerShare: 15,
      rewardRisk: 3,
      stopPct: -5,
      targetPct: 15,
      valid: true,
    });
    const short = positionStats("short", 200, 210, 175);
    expect(short.rewardRisk).toBe(2.5);
    expect(short.valid).toBe(true);
    expect(positionStats("long", 100, 105, 115).valid).toBe(false);
  });
});

describe("scene geometry", () => {
  it("draws a trend line between its anchors", () => {
    const s = shapes("trendline", [
      { ts: "2025-04-01", price: "100" },
      { ts: "2025-04-04", price: "130" },
    ]);
    expect(lines(s)).toMatchObject([{ x1: 0, y1: 100, x2: 30, y2: 70 }]);
  });

  it("extends a ray to the pane's right edge", () => {
    expect(rayEnd({ x: 0, y: 100 }, { x: 10, y: 90 }, 300, 200)).toEqual({ x: 300, y: -200 });
    const s = shapes("ray", [
      { ts: "2025-04-01", price: "100" },
      { ts: "2025-04-02", price: "100" },
    ]);
    expect(lines(s)).toMatchObject([{ x1: 0, y1: 100, x2: 300, y2: 100 }]);
  });

  it("labels a horizontal line with its price across the pane", () => {
    const s = shapes("hline", [{ ts: null, price: "150" }], "Support");
    expect(lines(s)).toMatchObject([{ x1: 0, y1: 50, x2: 300, y2: 50 }]);
    expect(texts(s)).toEqual(["Support 150.00"]);
  });

  it("fills a rectangle at its opacity", () => {
    const s = shapes("rectangle", [
      { ts: "2025-04-01", price: "120" },
      { ts: "2025-04-03", price: "100" },
    ]);
    expect(s[0]).toMatchObject({
      type: "poly",
      points: [
        [0, 80],
        [20, 80],
        [20, 100],
        [0, 100],
      ],
      opacity: DEFAULT_STYLE.fill_opacity,
    });
  });

  it("draws a parallel channel through the third anchor", () => {
    const s = shapes("channel", [
      { ts: "2025-04-01", price: "100" },
      { ts: "2025-04-03", price: "120" },
      { ts: "2025-04-02", price: "100" },
    ]);
    // The base line is at 110 on 2 Apr, so the parallel sits 10 lower.
    expect(lines(s)[1]).toMatchObject({ x1: 0, y1: 110, x2: 20, y2: 90 });
  });

  it("labels every Fibonacci level", () => {
    const s = shapes("fib_retracement", [
      { ts: "2025-04-01", price: "50" },
      { ts: "2025-04-04", price: "250" },
    ]);
    expect(texts(s)).toEqual([
      "0%  250.00",
      "23.6%  202.80",
      "38.2%  173.60",
      "50%  150.00",
      "61.8%  126.40",
      "78.6%  92.80",
      "100%  50.00",
    ]);
  });

  it("states the ruler's change, bars and days", () => {
    const s = shapes("ruler", [
      { ts: "2025-04-01", price: "100" },
      { ts: "2025-04-07", price: "110" },
    ]);
    expect(texts(s)).toEqual(["+10.00 (+10.00%) · 4 bars · 6 days"]);
  });

  it("draws the position tool's boxes, R:R and risk per share", () => {
    const s = shapes("position_long", [
      { ts: "2025-04-01", price: "100" },
      { ts: null, price: "95" },
      { ts: null, price: "115" },
    ]);
    const boxes = s.filter((x) => x.type === "poly");
    expect(boxes.map((b) => (b.type === "poly" ? b.fill : null))).toEqual(["green", "red"]);
    expect(texts(s)).toEqual([
      "Target 115.00 (+15.00%) · 3.00R",
      "Stop 95.00 (−5.00%) · −1R",
      "Long 100.00 · R:R 1:3.00 · risk 5.00/sh",
    ]);
  });

  it("adds handles to the selected drawing and the draft", () => {
    const d = {
      id: "7",
      kind: "trendline" as const,
      points: [
        { ts: "2025-04-01", price: "100" },
        { ts: "2025-04-02", price: "101" },
      ],
      style: DEFAULT_STYLE,
    };
    expect(buildScene([d], ctx, null).some((s) => s.type === "handle")).toBe(false);
    expect(buildScene([d], ctx, "7").filter((s) => s.type === "handle")).toHaveLength(2);
    expect(
      buildScene([{ ...d, id: "draft" }], ctx, null).filter((s) => s.type === "handle"),
    ).toHaveLength(2);
  });

  it("maps the same anchors onto weekly bars", () => {
    const weekly: SceneContext = {
      ...ctx,
      interval: "1wk",
      barDates: ["2025-03-28", "2025-04-04", "2025-04-11"],
    };
    const s = drawingShapes(
      {
        id: "1",
        kind: "trendline",
        points: [
          { ts: "2025-04-01", price: "100" },
          { ts: "2025-04-09", price: "120" },
        ],
        style: DEFAULT_STYLE,
      },
      weekly,
      false,
    );
    expect(lines(s)).toMatchObject([{ x1: 10, x2: 20 }]);
  });
});

describe("hit testing", () => {
  const scene = buildScene(
    [
      {
        id: "a",
        kind: "rectangle",
        points: [
          { ts: "2025-04-01", price: "150" },
          { ts: "2025-04-07", price: "100" },
        ],
        style: DEFAULT_STYLE,
      },
      {
        id: "b",
        kind: "trendline",
        points: [
          { ts: "2025-04-01", price: "120" },
          { ts: "2025-04-07", price: "120" },
        ],
        style: DEFAULT_STYLE,
      },
    ],
    ctx,
    "b",
  );

  it("prefers a handle, then a line, then a filled area", () => {
    expect(hitScene(scene, 1, 80)).toMatchObject({ id: "b", handle: 0 });
    expect(hitScene(scene, 20, 82)).toMatchObject({ id: "b", handle: null });
    expect(hitScene(scene, 20, 90)).toMatchObject({ id: "a", handle: null });
    expect(hitScene(scene, 200, 10)).toBeNull();
  });
});

function mockContext() {
  const calls: string[] = [];
  const record =
    (name: string) =>
    (...args: unknown[]) => {
      calls.push(
        `${name}(${args.map((a) => (typeof a === "number" ? Math.round(a) : JSON.stringify(a))).join(",")})`,
      );
    };
  const ctx2 = {
    save: record("save"),
    restore: record("restore"),
    beginPath: record("beginPath"),
    moveTo: record("moveTo"),
    lineTo: record("lineTo"),
    closePath: record("closePath"),
    stroke: record("stroke"),
    fill: record("fill"),
    fillRect: record("fillRect"),
    fillText: record("fillText"),
    arc: record("arc"),
    setLineDash: record("setLineDash"),
    measureText: (text: string) => ({ width: text.length * 6 }) as TextMetrics,
    strokeStyle: "",
    fillStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
    font: "",
    textAlign: "left" as CanvasTextAlign,
    textBaseline: "alphabetic" as CanvasTextBaseline,
  };
  return { ctx: ctx2 as unknown as PaintContext, calls, raw: ctx2 };
}

describe("painting", () => {
  it("strokes lines with their dash and writes labels over a backing", () => {
    const { ctx: c, calls, raw } = mockContext();
    const s = shapes("hline", [{ ts: null, price: "150" }]);
    paintScene(c, s, "Geist");
    expect(raw.font).toBe("11px Geist");
    expect(calls).toContain("moveTo(0,50)");
    expect(calls).toContain("lineTo(300,50)");
    expect(calls.filter((x) => x.startsWith("fillText"))).toEqual(['fillText("150.00",260,39)']);
    expect(calls.filter((x) => x.startsWith("fillRect"))).toHaveLength(1);
    expect(calls[0]).toBe("save()");
    expect(calls.at(-1)).toBe("restore()");
  });

  it("uses the dash pattern of the style", () => {
    const { ctx: c, calls } = mockContext();
    paintScene(
      c,
      drawingShapes(
        {
          id: "1",
          kind: "trendline",
          points: [
            { ts: "2025-04-01", price: "100" },
            { ts: "2025-04-02", price: "100" },
          ],
          style: { ...DEFAULT_STYLE, dash: "dashed" },
        },
        ctx,
        false,
      ),
      "Geist",
    );
    expect(calls).toContain("setLineDash([6,4])");
  });
});

describe("the primitive host", () => {
  it("builds shapes from the chart's coordinates and labels hlines on the price scale", () => {
    const primitive = new DrawingsPrimitive();
    const requestUpdate = vi.fn();
    primitive.attached({
      chart: {
        timeScale: () => ({
          logicalToCoordinate: (l: number) => l * 10,
          coordinateToLogical: (x: number) => x / 10,
          width: () => 300,
        }),
        panes: () => [{ getHeight: () => 200 }],
      },
      series: {
        priceToCoordinate: (p: number) => 200 - p,
        coordinateToPrice: (y: number) => 200 - y,
      },
      requestUpdate,
      horzScaleBehavior: {},
    } as never);
    primitive.setState({
      drawings: [
        { id: "1", kind: "hline", points: [{ ts: null, price: "150" }], style: DEFAULT_STYLE },
      ],
      selectedId: null,
      interval: "1d",
      barDates: BARS,
      palette: {
        ...COLOURS,
        positiveFill: "",
        negativeFill: "",
        grid: "",
        axis: "",
        line: "",
        areaTop: "",
        areaBottom: "",
        overlays: [],
      },
      fontFamily: "Geist",
    });
    expect(requestUpdate).toHaveBeenCalled();
    expect(primitive.shapes.some((s) => s.type === "line")).toBe(true);
    const axis = primitive.priceAxisViews();
    expect(axis).toHaveLength(1);
    expect(axis[0].coordinate()).toBe(50);
    expect(axis[0].text()).toBe("150.00");
    expect(primitive.hitTest(100, 51)).toMatchObject({
      externalId: "drawing:1",
      cursorStyle: "move",
    });
    expect(primitive.toChart(30, 100)).toEqual({ logical: 3, price: 100 });
    expect(primitive.paneViews()[0].renderer()).not.toBeNull();
  });
});

describe("undo history", () => {
  const drawing = {
    id: 1,
    ticker: "AAPL",
    kind: "hline" as const,
    points: [{ ts: null, price: "1" }],
    style: DEFAULT_STYLE,
    label: null,
    locked: false,
    created_at: "",
    updated_at: "",
  };

  it("undoes and redoes in order, and keeps ids after a re-create", () => {
    let h = record(EMPTY_HISTORY, { type: "create", drawing });
    h = record(h, { type: "delete", drawing });
    const undo = takeUndo(h);
    expect(undo?.entry.type).toBe("delete");
    expect(inverse(undo?.entry ?? { type: "create", drawing }).type).toBe("create");
    // The undo re-created it as id 9.
    h = remapId(undo?.next ?? EMPTY_HISTORY, 1, 9);
    expect(h.past[0]).toMatchObject({ type: "create", drawing: { id: 9 } });
    expect(h.future[0]).toMatchObject({ type: "delete", drawing: { id: 9 } });
    const redo = takeRedo(h);
    expect(redo?.entry).toMatchObject({ type: "delete", drawing: { id: 9 } });
    expect(takeUndo(EMPTY_HISTORY)).toBeNull();
    // A new change clears redo.
    expect(record(h, { type: "create", drawing }).future).toEqual([]);
  });

  it("inverts an update", () => {
    const after = { ...drawing, label: "x" };
    expect(inverse({ type: "update", before: drawing, after })).toEqual({
      type: "update",
      before: after,
      after: drawing,
    });
  });
});

describe("labels stay inside the pane", () => {
  it("right-aligns a label that would run off the right edge", async () => {
    const { fitLabel } = await import("@/lib/drawings/scene");
    expect(fitLabel(10, "short", "left", 300)).toEqual({ x: 10, align: "left" });
    expect(fitLabel(280, "Long 218.52 · R:R 1:2.08", "left", 300)).toEqual({
      x: 296,
      align: "right",
    });
    expect(fitLabel(5, "a long label here", "right", 300)).toEqual({ x: 4, align: "left" });
  });
});

describe("crowded Fibonacci levels", () => {
  it("draws every level but labels only those a line of text apart", () => {
    const s = drawingShapes(
      {
        id: "1",
        kind: "fib_retracement",
        points: [
          { ts: "2025-04-01", price: "100" },
          { ts: "2025-04-04", price: "130" },
        ],
        style: DEFAULT_STYLE,
      },
      ctx,
      false,
    );
    expect(s.filter((x) => x.type === "line")).toHaveLength(8);
    expect(
      s.filter((x) => x.type === "text").map((x) => (x.type === "text" ? x.text : "")),
    ).toEqual(["0%  130.00", "50%  115.00", "100%  100.00"]);
  });
});
