import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChartWorkbench, avwapKey, extremeDates } from "@/components/drawings/chart-workbench";
import { draftProblem } from "@/components/drawings/drawings-list";
import { dragPoints, placePoint } from "@/lib/drawings/drag";
import { DEFAULT_STYLE, type Drawing, describeDrawing, kindSpec } from "@/lib/drawings/kinds";
import { type SceneContext, avwapShapes, drawingShapes, hitScene } from "@/lib/drawings/scene";

import { resetLwc } from "../stubs/lightweight-charts";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const actions = vi.hoisted(() => ({
  createDrawingAction: vi.fn(),
  updateDrawingAction: vi.fn(),
  deleteDrawingAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/drawing-actions", () => actions);
const avwap = vi.hoisted(() => ({ avwapAction: vi.fn(), lastEarningsDateAction: vi.fn() }));
vi.mock("@/app/(product)/stocks/[ticker]/avwap-actions", () => avwap);

const bar = (ts: string, low: string, high: string) => ({
  ts: `${ts}T00:00:00`,
  open: low,
  high,
  low,
  close: high,
  volume: 100,
});
const BARS = [
  bar("2025-04-01", "100", "104"),
  bar("2025-04-02", "96", "101"), // lowest low
  bar("2025-04-03", "102", "109"), // highest high
  bar("2025-04-04", "103", "105"),
];

let nextId = 50;
function saved(input: Partial<Drawing>): Drawing {
  return {
    id: nextId++,
    ticker: "AAPL",
    kind: "avwap",
    points: [{ ts: "2025-04-02", price: null }],
    style: { ...DEFAULT_STYLE, bands: 1 },
    label: "swing",
    locked: false,
    created_at: "2026-11-26T00:00:00",
    updated_at: "2026-11-26T00:00:00",
    ...input,
  };
}

const AVWAP = {
  ticker: "AAPL",
  anchor: "2025-04-02",
  anchor_bar: "2025-04-02",
  interval: "1d",
  bands: 1,
  computed_from: "daily",
  decimals: 4,
  points: [
    { ts: "2025-04-02T00:00:00", vwap: 99, upper1: 99, lower1: 99 },
    { ts: "2025-04-03T00:00:00", vwap: 102, upper1: 104, lower1: 100 },
    { ts: "2025-04-04T00:00:00", vwap: 103, upper1: 105, lower1: 101 },
  ],
};

function renderBench(drawings: Drawing[] = [], interval: "1d" | "1wk" = "1d") {
  return render(
    <ChartWorkbench
      ticker="AAPL"
      signedIn
      initial={{
        ticker: "AAPL",
        drawings,
        limit: 200,
        first_bar: "2025-04-01",
        last_bar: "2025-04-04",
      }}
      callbackUrl="/stocks/AAPL"
      bars={BARS}
      interval={interval}
    />,
  );
}

beforeEach(() => {
  resetLwc();
  for (const fn of [...Object.values(actions), ...Object.values(avwap)]) fn.mockReset();
  actions.createDrawingAction.mockImplementation(async (input: Partial<Drawing>) => ({
    drawing: saved(input),
  }));
  avwap.avwapAction.mockResolvedValue({ avwap: AVWAP });
  avwap.lastEarningsDateAction.mockResolvedValue({ date: "2025-04-03" });
});

describe("the Anchored VWAP tool (A3.3)", () => {
  it("is in the toolbar and asks for one anchor bar, with a label and bands", async () => {
    const user = userEvent.setup();
    renderBench();
    const toolbar = screen.getByRole("toolbar", { name: "Drawing tools" });
    await user.click(within(toolbar).getByRole("button", { name: "Anchored VWAP" }));
    expect(screen.getByTestId("drawing-status").textContent).toContain(
      "Anchored VWAP: click the anchor bar (1 of 1)",
    );
    expect(screen.getByTestId("avwap-label")).toBeTruthy();
    expect((screen.getByTestId("avwap-bands") as HTMLSelectElement).value).toBe("1");
  });

  it("places a date-only anchor where the bar is clicked", () => {
    expect(
      placePoint(
        "avwap",
        0,
        { logical: 2.2, price: 150 },
        BARS.map((b) => b.ts.slice(0, 10)),
      ),
    ).toEqual({ ts: "2025-04-03", price: "" });
    const moved = dragPoints(
      "avwap",
      [{ ts: "2025-04-02", price: "" }],
      null,
      { logical: 1, price: 100 },
      { logical: 2, price: 140 },
      "1d",
      BARS.map((b) => b.ts.slice(0, 10)),
    );
    expect(moved).toEqual([{ ts: "2025-04-03", price: "" }]); // in time only
    expect(kindSpec("avwap").dateOnly).toBe(true);
  });

  it("anchors at the highest high and lowest low in view, and the last earnings date", async () => {
    const user = userEvent.setup();
    renderBench();
    expect(extremeDates(BARS)).toEqual({ high: "2025-04-03", low: "2025-04-02" });
    await user.click(screen.getByRole("button", { name: "Anchored VWAP" }));
    await user.type(screen.getByTestId("avwap-label"), "swing");
    await user.selectOptions(screen.getByTestId("avwap-bands"), "2");
    await user.click(screen.getByRole("button", { name: "Lowest low in view" }));
    await waitFor(() => expect(actions.createDrawingAction).toHaveBeenCalledTimes(1));
    expect(actions.createDrawingAction).toHaveBeenCalledWith({
      ticker: "AAPL",
      kind: "avwap",
      points: [{ ts: "2025-04-02", price: "" }],
      style: { ...DEFAULT_STYLE, bands: 2 },
      label: "swing",
      locked: false,
    });
    await user.click(screen.getByRole("button", { name: "Anchored VWAP" }));
    await user.click(screen.getByRole("button", { name: "Last earnings date" }));
    await waitFor(() => expect(actions.createDrawingAction).toHaveBeenCalledTimes(2));
    expect(avwap.lastEarningsDateAction).toHaveBeenCalledWith("AAPL", "2025-04-01", "2025-04-04");
    expect(actions.createDrawingAction.mock.calls[1][0].points).toEqual([
      { ts: "2025-04-03", price: "" },
    ]);
  });

  it("fetches each AVWAP's line for the chart's interval", async () => {
    const drawing = saved({ id: 7 });
    const { unmount } = renderBench([drawing]);
    await waitFor(() =>
      expect(avwap.avwapAction).toHaveBeenCalledWith("AAPL", "2025-04-02", "1d", 1),
    );
    expect(screen.getByTestId("price-chart").getAttribute("data-drawing-count")).toBe("1");
    expect(screen.getAllByTestId("drawing-item")[0].textContent).toContain(
      'Anchored VWAP "swing", from 2025-04-02, bands ±1σ',
    );
    unmount();
    renderBench([drawing], "1wk");
    await waitFor(() =>
      expect(avwap.avwapAction).toHaveBeenLastCalledWith("AAPL", "2025-04-02", "1wk", 1),
    );
    expect(avwapKey(drawing, "1d")).not.toBe(avwapKey(drawing, "1wk"));
    expect(avwapKey(drawing, "1d")).not.toBe(
      avwapKey({ ...drawing, style: { ...drawing.style, bands: 2 } }, "1d"),
    );
  });

  it("adds one by typing a date and a label, without a price", async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(screen.getByTestId("drawing-add-toggle"));
    await user.selectOptions(screen.getByTestId("drawing-add-kind"), "avwap");
    expect(screen.queryByTestId("drawing-price-0")).toBeNull();
    await user.click(screen.getByTestId("drawing-submit"));
    expect(screen.getByRole("alert").textContent).toContain("Give it a label");
    await user.type(screen.getByTestId("drawing-label"), "swing");
    await user.selectOptions(screen.getByTestId("drawing-bands"), "1");
    await user.click(screen.getByTestId("drawing-submit"));
    await waitFor(() => expect(actions.createDrawingAction).toHaveBeenCalledTimes(1));
    expect(actions.createDrawingAction).toHaveBeenCalledWith({
      ticker: "AAPL",
      kind: "avwap",
      points: [{ ts: "2025-04-04", price: "" }],
      style: { ...DEFAULT_STYLE, bands: 1 },
      label: "swing",
      locked: false,
    });
    expect(
      draftProblem(
        { kind: "avwap", points: [{ ts: "", price: "" }], label: "x", colour: "aqua" },
        { first: "2025-04-01", last: "2025-04-04" },
      ),
    ).toBe("Enter a date for the anchor bar.");
  });
});

describe("the AVWAP scene", () => {
  const ctx: SceneContext = {
    interval: "1d",
    barDates: ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"],
    xOfLogical: (l) => l * 10,
    yOfPrice: (p) => 200 - p,
    width: 300,
    height: 200,
    colours: {
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
    },
  };
  const line = AVWAP.points.map((p) => ({ ...p, date: p.ts.slice(0, 10) }));
  const drawing = {
    id: "7",
    kind: "avwap" as const,
    points: [{ ts: "2025-04-02", price: "" }],
    style: { ...DEFAULT_STYLE, bands: 1 },
    label: "swing",
    avwap: line,
  };

  it("draws the line, dashed bands, an anchor tick and a label at the right end", () => {
    const shapes = drawingShapes(drawing, ctx, false);
    const paths = shapes.filter((s) => s.type === "path");
    // One path per line: the vwap (wider) and the two bands (dashed).
    expect(paths).toHaveLength(3);
    const vwap = paths.find((s) => s.type === "path" && s.width === 2);
    expect(vwap).toMatchObject({
      dash: "solid",
      points: [
        [10, 101],
        [20, 98],
        [30, 97],
      ],
    });
    expect(paths.filter((s) => s.type === "path" && s.dash === "dashed")).toHaveLength(2);
    expect(shapes.filter((s) => s.type === "line")).toHaveLength(1); // the anchor tick
    // A click near the line selects it.
    expect(hitScene(shapes, 15, 99.5)?.id).toBe("7");
    const label = shapes.find((s) => s.type === "text");
    expect(label).toMatchObject({ text: "swing 103.00" });
  });

  it("shows only the anchor and label while its line loads, and a handle when selected", () => {
    const shapes = avwapShapes({ ...drawing, avwap: null }, ctx, true);
    expect(shapes.filter((s) => s.type === "line")).toHaveLength(1);
    expect(shapes.find((s) => s.type === "text")).toMatchObject({ text: "swing" });
    expect(shapes.find((s) => s.type === "handle")).toMatchObject({ x: 10, index: 0 });
  });

  it("is described with its anchor and bands", () => {
    expect(
      describeDrawing({
        kind: "avwap",
        points: [{ ts: "2025-04-02", price: null }],
        label: "swing",
        style: { bands: 2 },
      }),
    ).toBe('Anchored VWAP "swing", from 2025-04-02, bands ±1σ and ±2σ');
  });
});
