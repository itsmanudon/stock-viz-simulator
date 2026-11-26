/**
 * A6.7: the volume profile's geometry and primitive, the chart's context
 * menu (each alert is the alert form's own rule), and plan lines (drafts
 * drag and save, locked plans refuse).
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import { AlertForm } from "@/components/alert-form";
import {
  GRAB_PX,
  LOCKED_REASON,
  PlanLinesController,
  grabLine,
  movedPrices,
  planLines,
} from "@/components/plan-lines";
import { PriceChart, type PriceChartHandle } from "@/components/price-chart";
import {
  atrAt,
  drawingLevels,
  drawingRule,
  judgedNote,
  nearestStudy,
  planPrefill,
  priceAlertFields,
  ruleAlertFields,
  studyAlertFields,
  toFormData,
} from "@/lib/chart-menu";
import { DEFAULT_STYLE } from "@/lib/drawings/kinds";
import { volumeProfileShapes } from "@/lib/drawings/scene";
import { VolumeProfilePrimitive, paintProfiles } from "@/lib/drawings/volume-profile-primitive";
import type { TradePlan } from "@/lib/plans";
import {
  type VolumeProfile,
  debounce,
  parseProfileMode,
  profileGeometry,
  rangeOfBars,
  rangeOfSessions,
} from "@/lib/volume-profile";

import { resetLwc } from "../stubs/lightweight-charts";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
const createAlert = vi.hoisted(() =>
  vi.fn(async (input: unknown) => ({ id: 7, ticker: "AAPL", input })),
);
vi.mock("@/lib/api/alerts", () => ({
  createAlert: (input: unknown) => createAlert(input),
  deleteAlert: vi.fn(),
  dismissAlert: vi.fn(),
  rearmAlert: vi.fn(),
  setAlertPaused: vi.fn(),
}));
vi.mock("@/lib/api/server", () => ({
  AuthedApiError: class extends Error {},
  UnauthenticatedError: class extends Error {},
}));

// ---- Volume profile -------------------------------------------------------------

const PROFILE: VolumeProfile = {
  ticker: "AAPL",
  source: "minutes",
  feed: "sip",
  from: "2025-11-24T00:00:00",
  to: "2025-11-25T23:59:00",
  bars: 4,
  // The API's hand-checked set: bins 20, 100, 40, 50, 20 over 100-110.
  bins: [
    { low: "100", high: "102", volume: 20 },
    { low: "102", high: "104", volume: 100 },
    { low: "104", high: "106", volume: 40 },
    { low: "106", high: "108", volume: 50 },
    { low: "108", high: "110", volume: 20 },
  ],
  poc: "103",
  poc_index: 1,
  vah: "108",
  val: "102",
  value_area: 0.7,
  total_volume: 230,
  value_volume: 190,
  badges: ["From minute bars"],
  note: "Each bar's volume is spread evenly over its high-low range, so the profile is an approximation.",
};

// The stub's price scale: y = 200 - price.
const yOf = (price: number) => 200 - price;

describe("volume profile geometry (A6.7)", () => {
  it("scales bins to the longest and marks the value area and POC", () => {
    const g = profileGeometry(PROFILE, yOf, { anchor: 400, side: "left", maxWidth: 100 });
    expect(g.rects.map((r) => r.width)).toEqual([20, 100, 40, 50, 20]);
    // Growing leftwards from the right edge.
    expect(g.rects.map((r) => r.x)).toEqual([380, 300, 360, 350, 380]);
    expect(g.rects.map((r) => r.inValueArea)).toEqual([false, true, true, true, false]);
    expect(g.rects.map((r) => r.poc)).toEqual([false, true, false, false, false]);
    // Bin 102-104: top at y(104) = 96, 2 px tall less the 1 px gap.
    expect(g.rects[1]).toMatchObject({ y: 96, height: 1 });
    expect([g.pocY, g.vahY, g.valY]).toEqual([97, 92, 98]);
    expect([g.left, g.right]).toEqual([300, 400]);
  });

  it("grows rightwards from a fixed range's first session", () => {
    const g = profileGeometry(PROFILE, yOf, { anchor: 50, side: "right", maxWidth: 70 });
    expect(g.rects.every((r) => r.x === 50)).toBe(true);
    expect(g.rects[1].width).toBe(70);
  });

  it("asks for the bars' range: whole days, or intraday instants", () => {
    const daily = [{ ts: "2025-11-24T00:00:00" }, { ts: "2025-11-25T00:00:00" }];
    expect(rangeOfBars(daily, -3, 9)).toEqual({
      from: "2025-11-24T00:00:00Z",
      to: "2025-11-25T23:59:59Z",
    });
    const minutes = [
      { ts: "2025-11-24T14:30:00", closed_at: "2025-11-24T14:35:00" },
      { ts: "2025-11-24T14:35:00", closed_at: "2025-11-24T14:40:00" },
    ];
    expect(rangeOfBars(minutes, 0, 1)).toEqual({
      from: "2025-11-24T14:30:00Z",
      to: "2025-11-24T14:39:59Z",
    });
    expect(rangeOfBars([], 0, 1)).toBeNull();
    expect(rangeOfSessions("2025-11-25", "2025-11-24")).toEqual({
      from: "2025-11-24T00:00:00Z",
      to: "2025-11-25T23:59:59Z",
    });
    expect(parseProfileMode("visible")).toBe("visible");
    expect(parseProfileMode("nope")).toBe("off");
  });

  it("debounces the visible-range fetch", () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    const later = debounce(fn, 400);
    later(1);
    later(2);
    vi.advanceTimersByTime(399);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledExactlyOnceWith(2);
    later(3);
    later.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("paints bins under the candles, the POC solid and VAH/VAL dashed", () => {
    const calls: string[] = [];
    const context = {
      fillStyle: "",
      strokeStyle: "",
      globalAlpha: 1,
      lineWidth: 1,
      fillRect: () => calls.push(`rect:${context.fillStyle}`),
      beginPath: () => {},
      moveTo: () => {},
      lineTo: () => {},
      stroke: () => calls.push(`line:${context.strokeStyle}`),
      setLineDash: (d: number[]) => calls.push(`dash:${d.length}`),
      save: () => {},
      restore: () => {},
    };
    const g = profileGeometry(PROFILE, yOf, { anchor: 400, side: "left", maxWidth: 100 });
    paintProfiles(context, [g], { bins: "b", value: "v", poc: "p", levels: "l" });
    expect(calls.slice(0, 5)).toEqual(["rect:b", "rect:p", "rect:v", "rect:v", "rect:b"]);
    expect(calls.slice(5)).toEqual(["dash:0", "line:p", "dash:2", "line:l", "dash:2", "line:l"]);
  });

  it("the primitive lays a fixed range between its two bars", () => {
    const primitive = new VolumeProfilePrimitive({ bins: "b", value: "v", poc: "p", levels: "l" });
    const series = {
      priceToCoordinate: yOf,
    };
    const chart = {
      timeScale: () => ({ width: () => 400, logicalToCoordinate: (l: number) => l * 10 }),
    };
    primitive.attached({
      chart,
      series,
      requestUpdate: () => {},
    } as unknown as Parameters<VolumeProfilePrimitive["attached"]>[0]);
    primitive.setLayers([
      { key: "v", profile: PROFILE, placement: { kind: "right" } },
      { key: "f", profile: PROFILE, placement: { kind: "span", from: 2, to: 12 } },
    ]);
    const [visible, fixed] = primitive.shapes;
    // Visible: a quarter of the pane, from the right edge.
    expect(visible.right).toBe(400);
    expect(visible.left).toBe(300);
    // Fixed: from bar 2 (x 20), 70% of the 100 px between its bars.
    expect(fixed.left).toBe(20);
    expect(fixed.rects[1].width).toBeCloseTo(70);
  });

  it("draws a fixed range's bracket: an edge at each session, handles when selected", () => {
    const ctx = {
      interval: "1d" as const,
      barDates: ["2025-11-24", "2025-11-25", "2025-11-26"],
      xOfLogical: (l: number) => l * 10,
      yOfPrice: yOf,
      width: 300,
      height: 100,
      colours: {
        drawing: { ...DEFAULT_PALETTE },
        positive: "g",
        negative: "r",
        text: "t",
        labelBg: "bg",
      },
    };
    const d = {
      id: "5",
      kind: "volume_profile" as const,
      points: [
        { ts: "2025-11-24", price: "" },
        { ts: "2025-11-26", price: "" },
      ],
      style: DEFAULT_STYLE,
    };
    const shapes = volumeProfileShapes(d, ctx, true);
    const lines = shapes.filter((s) => s.type === "line");
    expect(lines.map((l) => (l.type === "line" ? l.x1 : null))).toEqual([0, 20]);
    expect(shapes.filter((s) => s.type === "handle")).toHaveLength(2);
  });
});

const DEFAULT_PALETTE = {
  aqua: "aqua",
  blue: "blue",
  violet: "violet",
  pink: "pink",
  amber: "amber",
  lime: "lime",
  slate: "slate",
  foreground: "fg",
};

// ---- The context menu's rules ---------------------------------------------------------

describe("chart menu rules (A6.7)", () => {
  it("builds a price alert towards the crosshair", () => {
    expect(priceAlertFields("AAPL", 123.456, 100)).toEqual({
      kind: "price",
      ticker: "AAPL",
      direction: "above",
      target_price: "123.46",
      repeat: "once",
    });
    expect(priceAlertFields("AAPL", 90, 100).direction).toBe("below");
  });

  it("builds a technical alert from the study, towards it", () => {
    expect(studyAlertFields("AAPL", "sma_50", 105, 100)).toMatchObject({
      kind: "technical",
      indicator: "close",
      op: "above",
      compare_to: "sma_50",
    });
    expect(studyAlertFields("AAPL", "bb_20_2.lower", 95, 100).op).toBe("below");
  });

  it("reads a drawing through A3.3's bindings, or says why not", () => {
    const hline = {
      kind: "hline" as const,
      label: "Swing High",
      points: [{ ts: null, price: "110" }],
    };
    expect(drawingRule(hline, "AAPL", 100, 110)).toMatchObject({
      rule: 'close crosses_above drawing("Swing High").price',
    });
    expect(drawingRule({ ...hline, kind: "avwap" }, "AAPL", 120, 110)).toMatchObject({
      rule: 'close crosses_below avwap("Swing High")',
    });
    const zone = {
      kind: "rectangle" as const,
      label: "Base",
      points: [
        { ts: "2025-01-02", price: "90" },
        { ts: "2025-01-09", price: "95" },
      ],
    };
    expect(drawingRule(zone, "AAPL", 100, 0)).toMatchObject({
      rule: 'close crosses_below drawing("Base").top',
    });
    expect(drawingRule(zone, "AAPL", 80, 0)).toMatchObject({
      rule: 'close crosses_above drawing("Base").bottom',
    });
    expect(drawingRule({ ...hline, label: null }, "AAPL", 100, 110)).toMatchObject({
      problem: expect.stringContaining("Label the drawing"),
    });
    expect(drawingRule({ ...hline, kind: "fib_retracement" }, "AAPL", 100, 110)).toMatchObject({
      problem: expect.stringContaining("Rules can read"),
    });
  });

  it("finds the study under the pointer", () => {
    const overlays = {
      sma_20: [{ ts: "2025-01-02T00:00:00", value: 101 }],
      sma_50: [{ ts: "2025-01-02T00:00:00", value: 120 }],
    };
    expect(nearestStudy(overlays, "2025-01-02T00:00:00", 100, yOf)).toEqual({
      key: "sma_20",
      value: 101,
    });
    expect(nearestStudy(overlays, "2025-01-02T00:00:00", 40, yOf)).toBeNull();
  });

  it("prefills a plan from the nearest drawings, else ATR and 2R", () => {
    const bars = [
      { high: 10, low: 8, close: 9 },
      { high: 11, low: 9, close: 10 },
      { high: 12, low: 9, close: 11 },
    ];
    expect(atrAt(bars, 2, 14)).toBe(2.5); // TR 2 and 3
    expect(planPrefill(100, [90, 95, 120, 130], 2)).toEqual({
      entry: "100.00",
      stop: "95.00",
      target: "120.00",
      stopFrom: "drawing",
      targetFrom: "drawing",
    });
    expect(planPrefill(100, [], 2)).toEqual({
      entry: "100.00",
      stop: "96.00",
      target: "108.00",
      stopFrom: "atr",
      targetFrom: "2r",
    });
    expect(
      drawingLevels([
        { id: "1", kind: "hline", points: [{ ts: null, price: "95" }] },
        { id: "2", kind: "text", points: [{ ts: "2025-01-02", price: "99" }] },
        { id: "draft", kind: "hline", points: [{ ts: null, price: "50" }] },
      ]),
    ).toEqual([95]);
    expect(judgedNote(false)).toContain("next stored bar");
    expect(judgedNote(true)).toContain("stream is running");
  });
});

// ---- Same rule as the form ------------------------------------------------------------------

async function viaAction(form: FormData): Promise<unknown> {
  createAlert.mockClear();
  const result = await createAlertAction({}, form);
  expect(result.error).toBeUndefined();
  expect(createAlert).toHaveBeenCalledTimes(1);
  return createAlert.mock.calls[0][0];
}

function formOf(container: HTMLElement): FormData {
  const form = container.querySelector("form");
  if (!form) throw new Error("no form");
  return new FormData(form);
}

describe("a chart alert is the alert form's rule (A6.7)", () => {
  it("price: the menu's fields create what the form creates", async () => {
    const { container } = render(<AlertForm ticker="AAPL" variant="inline" lastClose="100" />);
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByLabelText("Close"), { target: { value: "above" } });
    fireEvent.change(screen.getByLabelText(/^Target/), { target: { value: "123.45" } });
    const fromForm = await viaAction(formOf(container));
    const fromMenu = await viaAction(toFormData(priceAlertFields("AAPL", 123.4512, 100)));
    expect(fromMenu).toEqual(fromForm);
    expect(fromMenu).toEqual({
      ticker: "AAPL",
      direction: "above",
      target_price: "123.45",
      repeat: "once",
    });
  });

  it("indicator: the close crossing the study, as the form's series comparison", async () => {
    const { container } = render(<AlertForm ticker="AAPL" variant="inline" lastClose="100" />);
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "technical" } });
    fireEvent.change(screen.getByLabelText("When"), { target: { value: "close" } });
    fireEvent.change(screen.getByLabelText("Crosses"), { target: { value: "above" } });
    fireEvent.change(screen.getByLabelText("Or a series"), { target: { value: "sma_50" } });
    const fromForm = await viaAction(formOf(container));
    const fromMenu = await viaAction(toFormData(studyAlertFields("AAPL", "sma_50", 105, 100)));
    expect(fromMenu).toEqual(fromForm);
    expect(fromMenu).toMatchObject({ kind: "technical", params: { compare_to: "sma_50" } });
  });

  it("drawing: a rule alert on the saved setup, as the form's rule kind", async () => {
    const setups = [
      { versionId: 42, name: "AAPL: closes above", version: 1, canonical: "x", preset: false },
    ];
    const { container } = render(
      <AlertForm ticker="AAPL" variant="inline" lastClose="100" setups={setups} />,
    );
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByLabelText("Alert me on"), { target: { value: "rule" } });
    fireEvent.change(screen.getByLabelText("Saved setup"), { target: { value: "42" } });
    const fromForm = await viaAction(formOf(container));
    const fromMenu = await viaAction(toFormData(ruleAlertFields("AAPL", 42)));
    expect(fromMenu).toEqual(fromForm);
    expect(fromMenu).toEqual({
      ticker: "AAPL",
      kind: "rule",
      setup_version_id: 42,
      repeat: "once",
    });
  });
});

// ---- The chart hands its parts over -----------------------------------------------------------

const BARS = [
  { ts: "2025-04-01T00:00:00", open: "100", high: "101", low: "99", close: "100", volume: 10 },
  { ts: "2025-04-02T00:00:00", open: "100", high: "102", low: "99", close: "101", volume: 10 },
];

describe("PriceChart onChartReady (A6.7)", () => {
  beforeEach(() => resetLwc());

  it("hands the price series and the chart group to tools, and cleans up", () => {
    const cleanup = vi.fn();
    const ready = vi.fn((_handle: PriceChartHandle) => cleanup);
    const { unmount } = render(<PriceChart bars={BARS} onChartReady={ready} />);
    expect(ready).toHaveBeenCalledTimes(1);
    const handle = ready.mock.calls[0][0];
    expect(handle.root).toBe(screen.getByTestId("price-chart"));
    expect(handle.bars).toHaveLength(2);
    expect(handle.drawingAt(0, 0)).toBeNull();
    unmount();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });
});

// ---- Plan lines -------------------------------------------------------------------------------

function plan(overrides: Partial<TradePlan> = {}): TradePlan {
  return {
    id: 1,
    source: "paper",
    book_id: 1,
    replay_session_id: null,
    ticker: "AAPL",
    currency: "USD",
    side: "long",
    planned_entry: "100",
    planned_stop: "90",
    planned_target: "120",
    planned_size: "10",
    risk_per_share: "10",
    planned_risk: "100",
    reward_per_share: "20",
    reward_risk: "2.00",
    setup_version_id: null,
    setup_label: null,
    thesis_id: null,
    thesis_title: null,
    thesis_text: null,
    why: null,
    invalidation: null,
    horizon_bars: null,
    confidence: null,
    notes: null,
    tags: [],
    status: "open",
    locked: false,
    locked_at: null,
    first_fill_at: null,
    written_after_entry: false,
    frozen: false,
    fills: 0,
    created_at: "2026-11-26T00:00:00",
    updated_at: "2026-11-26T00:00:00",
    ...overrides,
  };
}

function fakeSeries() {
  const lines: { price: number; options: Record<string, unknown> }[] = [];
  return {
    lines,
    createPriceLine: (options: { price: number }) => {
      const line = {
        price: options.price,
        options: { ...options } as Record<string, unknown>,
        applyOptions: (o: { price?: number }) => {
          if (o.price !== undefined) line.price = o.price;
        },
      };
      lines.push(line);
      return line;
    },
    removePriceLine: (line: unknown) => {
      lines.splice(lines.indexOf(line as (typeof lines)[number]), 1);
    },
    priceToCoordinate: yOf,
    coordinateToPrice: (y: number) => 200 - y,
  };
}

function pointer(type: string, target: EventTarget, clientY: number) {
  target.dispatchEvent(
    new MouseEvent(type, { bubbles: true, cancelable: true, clientY, button: 0 }),
  );
}

describe("plan lines (A6.7)", () => {
  let root: HTMLDivElement;
  beforeEach(() => {
    root = document.createElement("div");
    document.body.append(root);
  });
  afterEach(() => {
    root.remove();
    vi.useRealTimers();
  });

  it("lists each plan's levels and grabs the nearest", () => {
    const lines = planLines([
      plan(),
      plan({ id: 2, planned_target: null, locked: true, status: "active" }),
    ]);
    expect(lines.map((l) => [l.planId, l.level, l.price, l.locked])).toEqual([
      [1, "entry", 100, false],
      [1, "stop", 90, false],
      [1, "target", 120, false],
      [2, "entry", 100, true],
      [2, "stop", 90, true],
    ]);
    // Entry 100 is at y 100, the target 120 at y 80, the stop 90 at y 110.
    const one = planLines([plan()]);
    expect(grabLine(one, 100 - GRAB_PX, yOf)?.level).toBe("entry");
    expect(grabLine(one, 100 - GRAB_PX - 1, yOf)).toBeNull();
    expect(grabLine(one, 108, yOf)?.level).toBe("stop");
  });

  it("refuses a move that breaks the plan, or any move on a locked plan", () => {
    expect(movedPrices(plan(), "stop", 95)).toEqual({
      entry: "100.00",
      stop: "95.00",
      target: "120.00",
    });
    expect(movedPrices(plan(), "stop", 105)).toMatchObject({
      problem: expect.stringContaining("stop"),
    });
    expect(movedPrices(plan(), "target", 99)).toMatchObject({
      problem: expect.stringContaining("target"),
    });
    expect(movedPrices(plan({ locked: true, status: "active" }), "stop", 95)).toEqual({
      problem: LOCKED_REASON,
    });
    expect(movedPrices(plan({ written_after_entry: true }), "stop", 95)).toEqual({
      problem: LOCKED_REASON,
    });
  });

  it("drags a draft's stop and saves it once, debounced", async () => {
    vi.useFakeTimers();
    const series = fakeSeries();
    const save = vi.fn(
      async (_id: number, prices: { entry: string; stop: string; target: string | null }) => ({
        plan: plan({ planned_stop: prices.stop }),
      }),
    );
    const onMessage = vi.fn();
    const controller = new PlanLinesController({
      series: series as never,
      root,
      container: root,
      colours: { entry: "e", stop: "s", target: "t" },
      save,
      onPlans: vi.fn(),
      onMessage,
      debounceMs: 600,
    });
    controller.setPlans([plan()]);
    expect(series.lines.map((l) => l.options.lineStyle)).toEqual([2, 2, 2]);
    // The stop (90) is at y 110: press it, drag to y 106 (price 94), release.
    pointer("pointerdown", root, 110);
    pointer("pointermove", window, 108);
    pointer("pointermove", window, 106);
    pointer("pointerup", window, 106);
    expect(controller.drawn().find((l) => l.level === "stop")?.price).toBe(94);
    // A second drag inside the debounce window: one save, with the last prices.
    pointer("pointerdown", root, 106);
    pointer("pointermove", window, 102);
    pointer("pointerup", window, 102);
    expect(save).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(save).toHaveBeenCalledExactlyOnceWith(1, {
      entry: "100.00",
      stop: "98.00",
      target: "120.00",
    });
    controller.destroy();
    expect(series.lines).toHaveLength(0);
  });

  it("draws a locked plan dotted and refuses a drag with A5.4's reason", () => {
    const series = fakeSeries();
    const save = vi.fn();
    const onMessage = vi.fn();
    const controller = new PlanLinesController({
      series: series as never,
      root,
      container: root,
      colours: { entry: "e", stop: "s", target: "t" },
      save,
      onPlans: vi.fn(),
      onMessage,
    });
    controller.setPlans([plan({ locked: true, frozen: true, status: "active", fills: 1 })]);
    expect(series.lines.map((l) => l.options.lineStyle)).toEqual([1, 1, 1]);
    expect(series.lines.map((l) => l.options.title)).toEqual([
      "Entry (Locked)",
      "Stop (Locked)",
      "Target (Locked)",
    ]);
    pointer("pointerdown", root, 110);
    pointer("pointermove", window, 100);
    pointer("pointerup", window, 100);
    expect(onMessage).toHaveBeenCalledWith(LOCKED_REASON);
    expect(series.lines.map((l) => l.price)).toEqual([100, 90, 120]);
    expect(save).not.toHaveBeenCalled();
    controller.destroy();
  });

  it("a refused save (the lock arrived) goes back to the saved prices", async () => {
    const series = fakeSeries();
    const onMessage = vi.fn();
    const controller = new PlanLinesController({
      series: series as never,
      root,
      container: root,
      colours: { entry: "e", stop: "s", target: "t" },
      save: async () => ({ error: "The plan is locked: it has a fill" }),
      onPlans: vi.fn(),
      onMessage,
      debounceMs: 10,
    });
    controller.setPlans([plan()]);
    pointer("pointerdown", root, 110);
    pointer("pointermove", window, 106);
    pointer("pointerup", window, 106);
    await waitFor(() =>
      expect(onMessage).toHaveBeenCalledWith("The plan is locked: it has a fill"),
    );
    expect(controller.drawn().find((l) => l.level === "stop")?.price).toBe(90);
    controller.destroy();
  });
});
