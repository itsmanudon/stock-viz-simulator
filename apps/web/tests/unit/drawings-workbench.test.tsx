import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChartWorkbench } from "@/components/drawings/chart-workbench";
import { draftProblem } from "@/components/drawings/drawings-list";
import { DEFAULT_STYLE, type Drawing } from "@/lib/drawings/kinds";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const actions = vi.hoisted(() => ({
  createDrawingAction: vi.fn(),
  updateDrawingAction: vi.fn(),
  deleteDrawingAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/drawing-actions", () => actions);
vi.mock("@/app/(product)/stocks/[ticker]/avwap-actions", () => ({
  avwapAction: vi.fn(async () => ({ error: "not in this test" })),
  lastEarningsDateAction: vi.fn(async () => ({ date: null })),
}));

const bar = (ts: string, close: string) => ({
  ts: `${ts}T00:00:00`,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
});
const BARS = [bar("2025-04-01", "100"), bar("2025-04-02", "101"), bar("2025-04-03", "102")];

let nextId = 10;
function saved(input: Partial<Drawing>): Drawing {
  return {
    id: nextId++,
    ticker: "AAPL",
    kind: "hline",
    points: [{ ts: null, price: "101" }],
    style: DEFAULT_STYLE,
    label: null,
    locked: false,
    created_at: "2026-11-26T00:00:00",
    updated_at: "2026-11-26T00:00:00",
    ...input,
  };
}

const INITIAL = {
  ticker: "AAPL",
  drawings: [
    saved({
      id: 1,
      kind: "trendline",
      points: [
        { ts: "2025-04-01", price: "100" },
        { ts: "2025-04-03", price: "102" },
      ],
    }),
  ],
  limit: 200,
  first_bar: "2025-04-01",
  last_bar: "2025-04-03",
};

function renderBench(props: Partial<Parameters<typeof ChartWorkbench>[0]> = {}) {
  return render(
    <ChartWorkbench
      ticker="AAPL"
      signedIn
      initial={INITIAL}
      callbackUrl="/stocks/AAPL"
      bars={BARS}
      {...props}
    />,
  );
}

beforeEach(() => {
  resetLwc();
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.createDrawingAction.mockImplementation(async (input: Partial<Drawing>) => ({
    drawing: saved(input),
  }));
  actions.deleteDrawingAction.mockResolvedValue({ ok: true });
  actions.updateDrawingAction.mockImplementation(async (id: number, changes: Partial<Drawing>) => ({
    drawing: { ...INITIAL.drawings[0], id, ...changes },
  }));
});

describe("ChartWorkbench", () => {
  it("names every tool and attaches one drawings primitive to the chart", () => {
    renderBench();
    const toolbar = screen.getByRole("toolbar", { name: "Drawing tools" });
    for (const name of [
      "Trend line",
      "Ray",
      "Horizontal line",
      "Rectangle",
      "Parallel channel",
      "Fib retracement",
      "Fib extension",
      "Measure",
      "Text note",
      "Long position",
      "Short position",
      "Anchored VWAP",
      "Undo",
      "Redo",
    ]) {
      expect(within(toolbar).getByRole("button", { name })).toBeTruthy();
    }
    expect(lwcCalls.primitives).toHaveLength(1);
    expect(screen.getByTestId("price-chart").getAttribute("data-drawing-count")).toBe("1");
    expect(screen.getAllByTestId("drawing-item")).toHaveLength(1);
  });

  it("disables the tools signed out and says why", () => {
    renderBench({ signedIn: false, initial: null });
    expect(
      screen.getByRole("link", { name: "Sign in to save drawings" }).getAttribute("href"),
    ).toBe("/login?callbackUrl=%2Fstocks%2FAAPL");
    expect(
      (screen.getByRole("button", { name: "Horizontal line" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(lwcCalls.primitives).toHaveLength(0);
  });

  it("presses a tool and prompts for its first anchor; Escape cancels", async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(screen.getByRole("button", { name: "Long position" }));
    expect(screen.getByRole("button", { name: "Long position" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByTestId("drawing-status").textContent).toContain("click entry (1 of 3)");
    expect(screen.getByTestId("price-chart").getAttribute("data-drawing-tool")).toBe(
      "position_long",
    );
    fireEvent.keyDown(screen.getByTestId("price-chart"), { key: "Escape" });
    expect(
      screen.getByRole("button", { name: "Select and move" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("adds a horizontal line by typing, then undoes and redoes it", async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(screen.getByTestId("drawing-add-toggle"));
    await user.type(screen.getByTestId("drawing-price-0"), "150.5");
    await user.type(screen.getByTestId("drawing-label"), "Resistance");
    await user.click(screen.getByTestId("drawing-submit"));
    await waitFor(() => expect(screen.getAllByTestId("drawing-item")).toHaveLength(2));
    expect(actions.createDrawingAction).toHaveBeenCalledWith({
      ticker: "AAPL",
      kind: "hline",
      points: [{ ts: null, price: "150.5" }],
      style: DEFAULT_STYLE,
      label: "Resistance",
      locked: false,
    });
    expect(screen.getAllByTestId("drawing-item")[1].textContent).toContain(
      'Horizontal line "Resistance", at 150.5',
    );

    const chart = screen.getByTestId("price-chart");
    fireEvent.keyDown(chart, { key: "z", ctrlKey: true });
    await waitFor(() => expect(screen.getAllByTestId("drawing-item")).toHaveLength(1));
    expect(actions.deleteDrawingAction).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(chart, { key: "z", ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(screen.getAllByTestId("drawing-item")).toHaveLength(2));
    expect(actions.createDrawingAction).toHaveBeenCalledTimes(2);
  });

  it("deletes the selected drawing with the Delete key", async () => {
    const user = userEvent.setup();
    renderBench();
    await user.click(screen.getByRole("button", { name: /^Trend line, 100 on 2025-04-01/ }));
    expect(screen.getByTestId("drawing-status").textContent).toContain("Selected: Trend line");
    fireEvent.keyDown(screen.getByTestId("price-chart"), { key: "Delete" });
    await waitFor(() => expect(screen.queryAllByTestId("drawing-item")).toHaveLength(0));
    expect(actions.deleteDrawingAction).toHaveBeenCalledWith(1);
  });

  it("shows the API's refusal", async () => {
    const user = userEvent.setup();
    actions.updateDrawingAction.mockResolvedValue({
      error: "The drawing is locked; unlock it first",
    });
    renderBench();
    await user.click(screen.getByRole("button", { name: "Lock" }));
    await waitFor(() =>
      expect(screen.getByTestId("drawing-status").textContent).toBe(
        "The drawing is locked; unlock it first",
      ),
    );
    expect(actions.updateDrawingAction).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ locked: true }),
    );
  });
});

describe("typed drawings are checked before they are sent", () => {
  const bounds = { first: "2025-04-01", last: "2025-04-03" };
  it("needs prices, dates in range and the right sides for a position", () => {
    expect(
      draftProblem(
        { kind: "hline", points: [{ ts: null, price: "" }], label: "", colour: "aqua" },
        bounds,
      ),
    ).toBe("Enter a price above 0 for the price.");
    expect(
      draftProblem(
        {
          kind: "rectangle",
          points: [
            { ts: "2025-03-01", price: "1" },
            { ts: "2025-04-02", price: "2" },
          ],
          label: "",
          colour: "aqua",
        },
        bounds,
      ),
    ).toContain("between 2025-04-01 and 2025-04-03");
    expect(
      draftProblem(
        {
          kind: "position_short",
          points: [
            { ts: "2025-04-02", price: "100" },
            { ts: null, price: "95" },
            { ts: null, price: "90" },
          ],
          label: "",
          colour: "aqua",
        },
        bounds,
      ),
    ).toBe("A short position needs target < entry < stop.");
    expect(
      draftProblem(
        { kind: "text", points: [{ ts: "2025-04-02", price: "1" }], label: " ", colour: "aqua" },
        bounds,
      ),
    ).toBe("A text note needs its text.");
  });
});
