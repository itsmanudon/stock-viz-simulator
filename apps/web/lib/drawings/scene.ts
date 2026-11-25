/**
 * Drawing geometry (A3.2): turns drawings (anchors in bar dates and prices)
 * into shapes in the price pane's CSS pixels, hit-tests those shapes, and
 * paints them on a 2D context. Pure apart from `paintScene`'s calls on the
 * context it is given, so the primitive host (`primitive.ts`) is a thin shell
 * and tests run without a canvas.
 */

import type { StockInterval } from "@/lib/stock-workspace";
import { anchorLogical } from "./anchor";
import type { DrawingColour, DrawingKind, DrawingPoint, DrawingStyle } from "./kinds";
import {
  fibExtension,
  fibRetracement,
  formatPrice,
  positionStats,
  rulerStats,
  signed,
} from "./math";

/** What the scene needs from the chart. */
export type SceneContext = {
  interval: StockInterval;
  /** Daily-bar dates of the loaded bars (YYYY-MM-DD), oldest first. */
  barDates: readonly string[];
  xOfLogical: (logical: number) => number | null;
  yOfPrice: (price: number) => number | null;
  width: number;
  height: number;
  colours: {
    drawing: Record<DrawingColour, string>;
    positive: string;
    negative: string;
    text: string;
    labelBg: string;
  };
};

/** A drawing as the scene draws it: a saved one, or the one being placed. */
export type SceneDrawing = {
  /** "draft" while it is being placed. */
  id: string;
  kind: DrawingKind;
  points: DrawingPoint[];
  style: DrawingStyle;
  label?: string | null;
  locked?: boolean;
};

type Dash = DrawingStyle["dash"];

export type Shape =
  | {
      type: "line";
      id: string;
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      colour: string;
      width: number;
      dash: Dash;
    }
  | {
      type: "poly";
      id: string;
      points: [number, number][];
      fill: string;
      opacity: number;
      stroke?: string;
      width?: number;
    }
  | {
      type: "text";
      id: string;
      x: number;
      y: number;
      text: string;
      colour: string;
      align: "left" | "right" | "center";
      bg?: string;
    }
  | {
      type: "handle";
      id: string;
      index: number;
      x: number;
      y: number;
      colour: string;
      ring: string;
    };

export type ScenePoint = { x: number; y: number; logical: number; price: number };

const FONT_PX = 11;
const POSITION_BARS = 25;
const HIT_PX = 6;

function px(p: DrawingPoint, prev: ScenePoint | null, ctx: SceneContext): ScenePoint | null {
  const price = Number(p.price);
  const y = ctx.yOfPrice(price);
  // A price-only point sits at the previous anchor's time.
  const logical = p.ts
    ? anchorLogical(p.ts, ctx.interval, ctx.barDates)
    : (prev?.logical ?? (ctx.barDates.length ? ctx.barDates.length - 1 : null));
  if (y === null || logical === null) return null;
  const x = ctx.xOfLogical(logical);
  if (x === null) return null;
  return { x, y, logical, price };
}

/** Resolve every anchor to pixels; null if any is off the scale. */
export function resolvePoints(points: DrawingPoint[], ctx: SceneContext): ScenePoint[] | null {
  const out: ScenePoint[] = [];
  for (const point of points) {
    const resolved = px(point, out.at(-1) ?? null, ctx);
    if (!resolved) return null;
    out.push(resolved);
  }
  return out;
}

function line(
  id: string,
  a: { x: number; y: number },
  b: { x: number; y: number },
  colour: string,
  width: number,
  dash: Dash = "solid",
): Shape {
  return { type: "line", id, x1: a.x, y1: a.y, x2: b.x, y2: b.y, colour, width, dash };
}

/** The point where a ray from a through b leaves the pane on the right. */
export function rayEnd(
  a: { x: number; y: number },
  b: { x: number; y: number },
  width: number,
  height: number,
): { x: number; y: number } {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) return b;
  if (dx === 0) return { x: a.x, y: dy > 0 ? height : 0 };
  const far = dx > 0 ? width : 0;
  return { x: far, y: a.y + (dy / dx) * (far - a.x) };
}

/** Shapes for one drawing. `selected` adds its anchor handles. */
export function drawingShapes(d: SceneDrawing, ctx: SceneContext, selected: boolean): Shape[] {
  const p = resolvePoints(d.points, ctx);
  if (!p || p.length === 0) return [];
  const colour = ctx.colours.drawing[d.style.colour] ?? ctx.colours.drawing.aqua;
  const w = d.style.width;
  const dash = d.style.dash;
  const fillOpacity = d.style.fill_opacity;
  const id = d.id;
  const shapes: Shape[] = [];
  const text = (
    x: number,
    y: number,
    value: string,
    align: "left" | "right" | "center",
    c = colour,
  ) => {
    const placed = fitLabel(x, value, align, ctx.width);
    shapes.push({
      type: "text",
      id,
      y,
      text: value,
      colour: c,
      bg: ctx.colours.labelBg,
      ...placed,
    });
  };

  switch (d.kind) {
    case "trendline":
      if (p.length < 2) break;
      shapes.push(line(id, p[0], p[1], colour, w, dash));
      break;
    case "ray":
      if (p.length < 2) break;
      shapes.push(line(id, p[0], rayEnd(p[0], p[1], ctx.width, ctx.height), colour, w, dash));
      break;
    case "hline": {
      const y = p[0].y;
      shapes.push(line(id, { x: 0, y }, { x: ctx.width, y }, colour, w, dash));
      text(
        ctx.width - 4,
        y - FONT_PX,
        `${d.label ? `${d.label} ` : ""}${formatPrice(p[0].price)}`,
        "right",
      );
      break;
    }
    case "rectangle": {
      if (p.length < 2) break;
      const [a, b] = p;
      shapes.push({
        type: "poly",
        id,
        points: [
          [a.x, a.y],
          [b.x, a.y],
          [b.x, b.y],
          [a.x, b.y],
        ],
        fill: colour,
        opacity: fillOpacity,
        stroke: colour,
        width: w,
      });
      if (d.label) text(Math.min(a.x, b.x) + 4, Math.min(a.y, b.y) + 2, d.label, "left");
      break;
    }
    case "channel": {
      if (p.length < 2) break;
      const [a, b] = p;
      shapes.push(line(id, a, b, colour, w, dash));
      if (p.length < 3) break;
      // The parallel side passes through the third anchor.
      const c = p[2];
      const t = b.x === a.x ? 0 : (c.x - a.x) / (b.x - a.x);
      const offset = c.y - (a.y + (b.y - a.y) * t);
      const a2 = { x: a.x, y: a.y + offset };
      const b2 = { x: b.x, y: b.y + offset };
      shapes.push({
        type: "poly",
        id,
        points: [
          [a.x, a.y],
          [b.x, b.y],
          [b2.x, b2.y],
          [a2.x, a2.y],
        ],
        fill: colour,
        opacity: fillOpacity,
      });
      shapes.push(line(id, a2, b2, colour, w, dash));
      shapes.push(
        line(
          id,
          { x: a.x, y: a.y + offset / 2 },
          { x: b.x, y: b.y + offset / 2 },
          colour,
          1,
          "dashed",
        ),
      );
      break;
    }
    case "fib_retracement":
    case "fib_extension": {
      if (p.length < 2) break;
      const [a, b] = p;
      const levels =
        d.kind === "fib_retracement"
          ? fibRetracement(a.price, b.price)
          : p.length >= 3
            ? fibExtension(a.price, b.price, p[2].price)
            : [];
      shapes.push(line(id, a, b, colour, 1, "dashed"));
      if (d.kind === "fib_extension" && p.length >= 3) {
        shapes.push(line(id, b, p[2], colour, 1, "dashed"));
      }
      const start = d.kind === "fib_extension" && p.length >= 3 ? p[2].x : Math.min(a.x, b.x);
      const span = Math.max(Math.abs(b.x - a.x), 40);
      const end = d.kind === "fib_extension" ? start + span : Math.max(a.x, b.x);
      // Labels closer than a line of text apart (a short swing, a monthly
      // chart) would overprint: the level is drawn, its label left out.
      const labelled: number[] = [];
      for (const level of levels) {
        const y = ctx.yOfPrice(level.price);
        if (y === null) continue;
        shapes.push(line(id, { x: start, y }, { x: end, y }, colour, w, dash));
        if (labelled.some((other) => Math.abs(other - y) < FONT_PX + 3)) continue;
        labelled.push(y);
        text(start + 2, y - FONT_PX - 1, `${level.label}  ${formatPrice(level.price)}`, "left");
      }
      break;
    }
    case "ruler": {
      if (p.length < 2) break;
      const [a, b] = p;
      const stats = rulerStats(
        { date: d.points[0].ts ?? "", price: a.price, logical: a.logical },
        { date: d.points[1].ts ?? "", price: b.price, logical: b.logical },
      );
      const tone = stats.deltaPrice >= 0 ? ctx.colours.positive : ctx.colours.negative;
      shapes.push({
        type: "poly",
        id,
        points: [
          [a.x, a.y],
          [b.x, a.y],
          [b.x, b.y],
          [a.x, b.y],
        ],
        fill: tone,
        opacity: Math.max(fillOpacity, 0.08),
      });
      shapes.push(line(id, a, b, tone, w, dash));
      text(
        (a.x + b.x) / 2,
        Math.min(a.y, b.y) - FONT_PX - 6,
        `${signed(stats.deltaPrice)} (${signed(stats.deltaPct)}%) · ${stats.bars} bars · ${stats.days} days`,
        "center",
        tone,
      );
      break;
    }
    case "text":
      text(p[0].x, p[0].y - FONT_PX / 2, d.label || "Note", "left");
      break;
    case "position_long":
    case "position_short": {
      const entry = p[0];
      const right = ctx.xOfLogical(entry.logical + POSITION_BARS) ?? ctx.width;
      const x2 = Math.min(Math.max(right, entry.x + 40), ctx.width);
      shapes.push(line(id, { x: entry.x, y: entry.y }, { x: x2, y: entry.y }, colour, w, "solid"));
      if (p.length < 3) {
        if (p.length === 2) {
          shapes.push(box(id, entry.x, x2, entry.y, p[1].y, ctx.colours.negative, 0.18));
        }
        break;
      }
      const [, stop, target] = p;
      const side = d.kind === "position_long" ? "long" : "short";
      const stats = positionStats(side, entry.price, stop.price, target.price);
      shapes.push(box(id, entry.x, x2, entry.y, target.y, ctx.colours.positive, 0.18));
      shapes.push(box(id, entry.x, x2, entry.y, stop.y, ctx.colours.negative, 0.18));
      const r = stats.rewardRisk.toFixed(2);
      text(
        entry.x + 4,
        target.y + (target.y < entry.y ? 2 : -FONT_PX - 4),
        `Target ${formatPrice(target.price)} (${signed(stats.targetPct)}%) · ${r}R`,
        "left",
        ctx.colours.positive,
      );
      text(
        entry.x + 4,
        stop.y + (stop.y < entry.y ? 2 : -FONT_PX - 4),
        `Stop ${formatPrice(stop.price)} (${signed(stats.stopPct)}%) · −1R`,
        "left",
        ctx.colours.negative,
      );
      text(
        entry.x + 4,
        entry.y + (target.y < entry.y ? 3 : -FONT_PX - 5),
        `${side === "long" ? "Long" : "Short"} ${formatPrice(entry.price)} · R:R 1:${r} · risk ${formatPrice(stats.riskPerShare)}/sh${stats.valid ? "" : " · check sides"}`,
        "left",
        ctx.colours.text,
      );
      break;
    }
  }

  if (selected) {
    p.forEach((point, index) => {
      const hx =
        d.kind === "hline" ? Math.min(ctx.width - 12, Math.max(12, ctx.width / 2)) : point.x;
      shapes.push({ type: "handle", id, index, x: hx, y: point.y, colour, ring: ctx.colours.text });
    });
  }
  return shapes;
}

/** Estimated label width in CSS pixels (11px Geist, with the backing). */
export function labelWidth(text: string): number {
  return text.length * FONT_PX * 0.6 + 8;
}

/**
 * Keep a label inside the pane: one that would run past the right edge is
 * right-aligned to it, one past the left edge left-aligned to it.
 */
export function fitLabel(
  x: number,
  text: string,
  align: "left" | "right" | "center",
  width: number,
): { x: number; align: "left" | "right" | "center" } {
  const w = labelWidth(text);
  const left = align === "left" ? x : align === "right" ? x - w : x - w / 2;
  if (left + w > width - 2) return { x: width - 4, align: "right" };
  if (left < 2) return { x: 4, align: "left" };
  return { x, align };
}

function box(
  id: string,
  x1: number,
  x2: number,
  y1: number,
  y2: number,
  fill: string,
  opacity: number,
): Shape {
  return {
    type: "poly",
    id,
    points: [
      [x1, y1],
      [x2, y1],
      [x2, y2],
      [x1, y2],
    ],
    fill,
    opacity,
  };
}

export function buildScene(
  drawings: readonly SceneDrawing[],
  ctx: SceneContext,
  selectedId: string | null,
): Shape[] {
  return drawings.flatMap((d) => drawingShapes(d, ctx, d.id === selectedId || d.id === "draft"));
}

function segmentDistance(px0: number, py0: number, s: Extract<Shape, { type: "line" }>): number {
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  const len2 = dx * dx + dy * dy;
  const t =
    len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px0 - s.x1) * dx + (py0 - s.y1) * dy) / len2));
  return Math.hypot(px0 - (s.x1 + t * dx), py0 - (s.y1 + t * dy));
}

function insidePoly(x: number, y: number, points: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function textBox(s: Extract<Shape, { type: "text" }>) {
  const width = labelWidth(s.text);
  const left =
    s.align === "left" ? s.x - 4 : s.align === "right" ? s.x - width + 4 : s.x - width / 2;
  return { left, top: s.y - 2, width, height: FONT_PX + 6 };
}

export type Hit = { id: string; handle: number | null; distance: number };

/**
 * The topmost shape under (x, y): a handle first, then a line or a label
 * within HIT_PX, then a filled area. Later drawings sit on top.
 */
export function hitScene(shapes: readonly Shape[], x: number, y: number): Hit | null {
  let best: Hit | null = null;
  let bestRank = -1;
  for (let i = shapes.length - 1; i >= 0; i--) {
    const s = shapes[i];
    let rank = -1;
    let distance = Number.POSITIVE_INFINITY;
    if (s.type === "handle") {
      distance = Math.hypot(x - s.x, y - s.y);
      if (distance <= HIT_PX + 2) rank = 3;
    } else if (s.type === "line") {
      distance = segmentDistance(x, y, s);
      if (distance <= HIT_PX) rank = 2;
    } else if (s.type === "text") {
      const b = textBox(s);
      if (x >= b.left && x <= b.left + b.width && y >= b.top && y <= b.top + b.height) {
        rank = 2;
        distance = 0;
      }
    } else if (s.type === "poly" && insidePoly(x, y, s.points)) {
      rank = 1;
      distance = 0;
    }
    if (rank > bestRank || (rank === bestRank && rank >= 0 && best && distance < best.distance)) {
      bestRank = rank;
      best = { id: s.id, handle: s.type === "handle" ? s.index : null, distance };
    }
  }
  return bestRank >= 0 ? best : null;
}

/** The subset of CanvasRenderingContext2D the painter uses. */
export type PaintContext = Pick<
  CanvasRenderingContext2D,
  | "save"
  | "restore"
  | "beginPath"
  | "moveTo"
  | "lineTo"
  | "closePath"
  | "stroke"
  | "fill"
  | "fillRect"
  | "fillText"
  | "arc"
  | "setLineDash"
  | "measureText"
> & {
  strokeStyle: CanvasRenderingContext2D["strokeStyle"];
  fillStyle: CanvasRenderingContext2D["fillStyle"];
  lineWidth: number;
  globalAlpha: number;
  font: string;
  textAlign: CanvasTextAlign;
  textBaseline: CanvasTextBaseline;
};

const DASHES: Record<Dash, number[]> = { solid: [], dashed: [6, 4], dotted: [1.5, 3] };

export function paintScene(c: PaintContext, shapes: readonly Shape[], fontFamily: string): void {
  c.save();
  c.font = `${FONT_PX}px ${fontFamily}`;
  c.textBaseline = "top";
  for (const s of shapes) {
    if (s.type === "poly") {
      c.beginPath();
      s.points.forEach(([x, y], i) => (i === 0 ? c.moveTo(x, y) : c.lineTo(x, y)));
      c.closePath();
      c.globalAlpha = s.opacity;
      c.fillStyle = s.fill;
      c.fill();
      c.globalAlpha = 1;
      if (s.stroke) {
        c.setLineDash([]);
        c.strokeStyle = s.stroke;
        c.lineWidth = s.width ?? 1;
        c.stroke();
      }
    } else if (s.type === "line") {
      c.beginPath();
      c.setLineDash(DASHES[s.dash]);
      c.strokeStyle = s.colour;
      c.lineWidth = s.width;
      c.moveTo(s.x1, s.y1);
      c.lineTo(s.x2, s.y2);
      c.stroke();
      c.setLineDash([]);
    } else if (s.type === "text") {
      const width = c.measureText(s.text).width;
      const left = s.align === "left" ? s.x : s.align === "right" ? s.x - width : s.x - width / 2;
      if (s.bg) {
        c.fillStyle = s.bg;
        c.fillRect(left - 3, s.y - 2, width + 6, FONT_PX + 5);
      }
      c.textAlign = "left";
      c.fillStyle = s.colour;
      c.fillText(s.text, left, s.y);
    } else {
      c.beginPath();
      c.arc(s.x, s.y, 4.5, 0, Math.PI * 2);
      c.fillStyle = s.colour;
      c.fill();
      c.lineWidth = 1.5;
      c.strokeStyle = s.ring;
      c.stroke();
    }
  }
  c.restore();
}
