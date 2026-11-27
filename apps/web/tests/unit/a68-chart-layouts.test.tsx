/**
 * A6.8 (M2.10): the chart workspace's URL state, linked groups, crosshair
 * placement, and the workspace components (PriceChart stubbed). Synthetic
 * symbols and bars only.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  type WorkspaceState,
  chooseColourSymbol,
  chooseGrid,
  choosePaneLink,
  choosePaneSymbol,
  layoutBody,
  layoutState,
  parseWorkspace,
  workspaceHref,
} from "@/lib/chart-layouts";
import type { PaneView } from "@/lib/chart-layouts-server";
import { syncedBarIndex } from "@/lib/chart-sync";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));
vi.mock("@/app/(product)/(authed)/charts/actions", () => ({
  saveLayoutAction: vi.fn(async () => ({ ok: true, id: 9 })),
  deleteLayoutAction: vi.fn(async () => ({ ok: true })),
  deleteTemplateAction: vi.fn(async () => ({ ok: true })),
  createTemplateAction: vi.fn(async () => ({ ok: true, id: 4 })),
}));

type ChartProps = {
  bars: unknown[];
  interval: string;
  chartType: string;
  crosshairTime?: number | null;
  onCrosshairTime?: (time: number | null) => void;
  paneHeights?: Record<string, number>;
};
const charts = new Map<string, ChartProps>();
vi.mock("@/components/price-chart", () => ({
  PriceChart: (props: ChartProps & { bars: { ts: string }[] }) => {
    const key = `${props.interval}:${props.bars[0]?.ts ?? ""}`;
    charts.set(key, props);
    return (
      <div
        data-testid="stub-chart"
        data-key={key}
        data-crosshair={
          props.crosshairTime === undefined ? "unsynced" : String(props.crosshairTime)
        }
      />
    );
  },
}));

const { LayoutWorkspace } = await import("@/components/chart-layouts/layout-workspace");
const { LayoutLibrary } = await import("@/components/chart-layouts/layout-library");
const { templateHeights } = await import("@/components/chart-layouts/save-template-button");
const actions = await import("@/app/(product)/(authed)/charts/actions");

function four(): WorkspaceState {
  return parseWorkspace({
    grid: "4",
    s: "AAA,AAA,BBB,CCC",
    i: "1wk,15m,1d,1d",
    t: "3,,3,",
    g: "blue,blue,pink,",
  });
}

function okView(symbol: string, interval: string, firstTs: string): PaneView {
  return {
    status: "ok",
    symbol,
    name: `${symbol} Inc.`,
    interval: interval as never,
    note: null,
    templateName: null,
    chartType: "candles",
    scale: "linear",
    paneHeights: null,
    indicators: [],
    bars: [{ ts: firstTs, open: "1", high: "1", low: "1", close: "1", volume: 1 }] as never,
    overlays: {},
    panes: [],
    rsi: null,
    macd: null,
    timeZone: "UTC",
    sourceFeed: null,
  };
}

function hrefState(href: string): WorkspaceState {
  const params = new URL(href, "http://x").searchParams;
  return parseWorkspace(Object.fromEntries(params.entries()));
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  charts.clear();
});

describe("workspace URL state", () => {
  it("round-trips a four-pane layout through the URL", () => {
    const state = four();
    expect(state.panes).toEqual([
      { symbol: "AAA", interval: "1wk", templateId: 3, link: "blue" },
      { symbol: "AAA", interval: "15m", templateId: null, link: "blue" },
      { symbol: "BBB", interval: "1d", templateId: 3, link: "pink" },
      { symbol: "CCC", interval: "1d", templateId: null, link: null },
    ]);
    const href = workspaceHref(state, 7);
    expect(href).toBe(
      "/charts?grid=4&s=AAA%2CAAA%2CBBB%2CCCC&i=1wk%2C15m%2C1d%2C1d&t=3%2C%2C3%2C&g=blue%2Cblue%2Cpink%2C&layout=7",
    );
    expect(hrefState(href)).toEqual(state);
  });

  it("leaves out templates and links when there are none, and fills a short URL", () => {
    expect(workspaceHref(parseWorkspace({ grid: "2v", s: "aaa" }))).toBe(
      "/charts?grid=2v&s=AAA%2CAAA&i=1d%2C1d",
    );
    const junk = parseWorkspace({ grid: "9", s: "<x>", i: "2h", t: "-1", g: "teal" });
    expect(junk).toEqual({
      grid: "1",
      panes: [{ symbol: "AAPL", interval: "1d", templateId: null, link: null }],
      watchlistLink: null,
    });
  });

  it("reads a colour that disagrees with itself with its first pane's symbol", () => {
    const state = parseWorkspace({ grid: "2h", s: "AAA,BBB", g: "lime,lime" });
    expect(state.panes.map((p) => p.symbol)).toEqual(["AAA", "AAA"]);
  });

  it("maps a saved layout to state and back to the API body", () => {
    const layout = {
      grid: "2v",
      panes: [
        { symbol: "AAA", interval: "60m", template_id: 5, link: "amber" },
        { symbol: "BBB", interval: "1mo", template_id: null, link: null },
      ],
    };
    expect(layoutBody(layoutState(layout))).toEqual(layout);
  });
});

describe("linked groups", () => {
  it("a symbol chosen in blue moves every blue pane and nothing else", () => {
    const next = choosePaneSymbol(four(), 1, "ZZZ");
    expect(next.panes.map((p) => p.symbol)).toEqual(["ZZZ", "ZZZ", "BBB", "CCC"]);
    // Intervals and templates stay each pane's own.
    expect(next.panes.map((p) => p.interval)).toEqual(["1wk", "15m", "1d", "1d"]);
    expect(choosePaneSymbol(four(), 3, "QQQ").panes.map((p) => p.symbol)).toEqual([
      "AAA",
      "AAA",
      "BBB",
      "QQQ",
    ]);
    expect(chooseColourSymbol(four(), "pink", "YYY").panes.map((p) => p.symbol)).toEqual([
      "AAA",
      "AAA",
      "YYY",
      "CCC",
    ]);
  });

  it("a pane joining a colour takes its symbol; leaving keeps its own", () => {
    const joined = choosePaneLink(four(), 3, "blue");
    expect(joined.panes[3]).toMatchObject({ symbol: "AAA", link: "blue" });
    const left = choosePaneLink(four(), 0, null);
    expect(left.panes[0]).toMatchObject({ symbol: "AAA", link: null });
    // A colour nobody else is in keeps the pane's symbol.
    expect(choosePaneLink(four(), 3, "slate").panes[3]).toMatchObject({ symbol: "CCC" });
  });

  it("a new grid keeps the first panes and starts new ones unlinked", () => {
    const one = chooseGrid(four(), "1");
    expect(one.panes).toHaveLength(1);
    const back = chooseGrid(one, "4");
    expect(back.panes.slice(1)).toEqual([
      { symbol: "AAA", interval: "1d", templateId: null, link: null },
      { symbol: "AAA", interval: "1d", templateId: null, link: null },
      { symbol: "AAA", interval: "1d", templateId: null, link: null },
    ]);
  });
});

describe("syncedBarIndex", () => {
  const day = 86_400;
  const mon = Date.UTC(2026, 10, 16) / 1000;
  const daily = [mon, mon + day, mon + 2 * day, mon + 3 * day, mon + 4 * day];

  it("puts a time on the bar that starts at or before it (intraday, daily)", () => {
    expect(syncedBarIndex(daily, mon + 2 * day + 14.5 * 3600, "1d")).toBe(2);
    expect(syncedBarIndex(daily, mon + day, "1d")).toBe(1);
    expect(syncedBarIndex(daily, mon - 60, "1d")).toBeNull();
    const minutes = [mon + 34_200, mon + 34_500, mon + 34_800];
    expect(syncedBarIndex(minutes, mon + 34_600, "5m")).toBe(1);
    expect(syncedBarIndex(minutes, mon, "5m")).toBeNull();
  });

  it("puts a time on the week or month whose last session is on or after its day", () => {
    const weeks = [mon - 3 * day, mon + 4 * day, mon + 11 * day];
    expect(syncedBarIndex(weeks, mon + 2 * day + 15 * 3600, "1wk")).toBe(1);
    expect(syncedBarIndex(weeks, mon + 4 * day, "1wk")).toBe(1);
    expect(syncedBarIndex(weeks, mon + 12 * day, "1wk")).toBeNull();
    expect(syncedBarIndex([], mon, "1d")).toBeNull();
  });
});

describe("templateHeights", () => {
  it("keeps the remembered heights the API accepts", () => {
    expect(
      templateHeights({ price: 312.4, volume: 20, rsi: 1300, "bad key": 100, macd: 140 }),
    ).toEqual({ price: 312, macd: 140 });
  });
});

describe("LayoutWorkspace", () => {
  const views = [
    okView("AAA", "1wk", "2026-01-02T00:00:00Z"),
    okView("AAA", "15m", "2026-01-02T14:30:00Z"),
    okView("BBB", "1d", "2026-01-03T00:00:00Z"),
    { status: "missing", symbol: "CCC" } as PaneView,
  ];
  const templates = [{ id: 3, name: "Trend" }];

  function renderWorkspace(state = four(), watchlist = [{ ticker: "WWW", name: "W" }]) {
    return render(
      <LayoutWorkspace
        state={state}
        views={views}
        layoutId={7}
        layoutName="Desk"
        layoutMissing={false}
        templates={templates}
        watchlist={watchlist}
      />,
    );
  }

  it("changing the symbol in the blue group moves every blue widget and nothing else", async () => {
    const user = userEvent.setup();
    renderWorkspace({ ...four(), watchlistLink: "blue" });
    const input = screen.getByLabelText("Symbol for chart 2");
    await user.clear(input);
    await user.type(input, "zzz{Enter}");
    expect(push).toHaveBeenCalledTimes(1);
    const moved = hrefState(push.mock.calls[0][0]);
    expect(moved.panes.map((p) => p.symbol)).toEqual(["ZZZ", "ZZZ", "BBB", "CCC"]);
    expect(moved.panes.map((p) => p.link)).toEqual(["blue", "blue", "pink", null]);
    expect(moved.watchlistLink).toBe("blue");
    expect(push.mock.calls[0][0]).toContain("layout=7");

    // The blue watchlist drives the blue panes too.
    const watchlist = screen.getByTestId("layout-watchlist");
    expect(within(watchlist).getByRole("button", { name: "WWW" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(within(watchlist).getByRole("button", { name: "WWW" }));
    const fromList = hrefState(push.mock.calls[1][0]);
    expect(fromList.panes.map((p) => p.symbol)).toEqual(["WWW", "WWW", "BBB", "CCC"]);
  });

  it("marks the watchlist row its colour follows, and links rows when unlinked", () => {
    const { unmount } = renderWorkspace({
      ...parseWorkspace({ grid: "2v", s: "WWW,BBB", g: "lime," }),
      watchlistLink: "lime",
    });
    expect(screen.getByRole("button", { name: "WWW" })).toHaveAttribute("aria-pressed", "true");
    unmount();
    renderWorkspace();
    expect(screen.getByRole("link", { name: "WWW" })).toHaveAttribute("href", "/stocks/WWW");
  });

  it("shares the crosshair time with the panes on the same symbol only", () => {
    renderWorkspace();
    const source = charts.get("1wk:2026-01-02T00:00:00Z");
    expect(source).toBeDefined();
    act(() => source?.onCrosshairTime?.(1_767_312_000));
    const crosshairs = screen.getAllByTestId("stub-chart").map((el) => el.dataset.crosshair);
    // Pane 1 (the source) is not synced; pane 2 is AAA too; pane 3 is BBB.
    expect(crosshairs).toEqual(["unsynced", "1767312000", "null"]);
    act(() => source?.onCrosshairTime?.(null));
    expect(screen.getAllByTestId("stub-chart").map((el) => el.dataset.crosshair)).toEqual([
      "unsynced",
      "null",
      "null",
    ]);
  });

  it("says when a saved layout's symbol is missing, and keeps the pane's controls", () => {
    renderWorkspace();
    const pane = screen.getByTestId("chart-pane-3");
    expect(within(pane).getByTestId("pane-missing")).toHaveTextContent("CCC is not a symbol");
    expect(within(pane).getByLabelText("Symbol for chart 4")).toHaveValue("CCC");
  });

  it("moves between the phone tabs with the arrow keys", () => {
    renderWorkspace();
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(screen.getAllByRole("tab")[3]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("chart-pane-0").parentElement).toHaveClass("max-md:hidden");
  });

  it("changes the grid, the interval and the template through the URL", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.selectOptions(screen.getByLabelText("Interval for chart 3"), "60m");
    expect(hrefState(push.mock.calls[0][0]).panes[2].interval).toBe("60m");
    await user.selectOptions(screen.getByLabelText("Template for chart 4"), "3");
    expect(hrefState(push.mock.calls[1][0]).panes[3].templateId).toBe(3);
    await user.selectOptions(screen.getByLabelText("Grid"), "2h");
    expect(hrefState(push.mock.calls[2][0]).grid).toBe("2h");
    await user.selectOptions(screen.getByLabelText("Link colour for chart 4"), "pink");
    expect(hrefState(push.mock.calls[3][0]).panes[3]).toMatchObject({
      link: "pink",
      symbol: "BBB",
    });
  });

  it("saves the layout over the open one, then opens it", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(actions.saveLayoutAction).toHaveBeenCalledWith(7, {
      name: "Desk",
      ...layoutBody(four()),
    });
    expect(push).toHaveBeenLastCalledWith(workspaceHref(four(), 9));
  });
});

describe("LayoutLibrary", () => {
  it("shows the empty and error states", () => {
    const { unmount } = render(<LayoutLibrary layouts={[]} templates={[]} currentId={null} />);
    expect(screen.getByTestId("layouts-empty")).toHaveTextContent("No saved layouts yet.");
    expect(screen.getByTestId("templates-empty")).toBeInTheDocument();
    unmount();
    render(<LayoutLibrary layouts={null} templates={null} currentId={null} />);
    expect(screen.getByTestId("layouts-error")).toHaveTextContent("could not load");
  });

  it("lists saved layouts with links and deletes one", async () => {
    const user = userEvent.setup();
    render(
      <LayoutLibrary
        layouts={[
          {
            id: 5,
            name: "Desk",
            grid: "4",
            panes: [],
            created_at: "2026-11-26T00:00:00Z",
            updated_at: "2026-11-26T00:00:00Z",
          },
        ]}
        templates={[]}
        currentId={5}
      />,
    );
    expect(screen.getByRole("link", { name: /Desk/ })).toHaveAttribute("href", "/charts?layout=5");
    expect(screen.getByRole("link", { name: /Desk/ })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "Delete layout Desk" }));
    expect(actions.deleteLayoutAction).toHaveBeenCalledWith(5);
    expect(push).toHaveBeenCalledWith("/charts");
  });
});
