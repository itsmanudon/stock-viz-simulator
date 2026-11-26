/**
 * A6.7: the stock chart's tools wired to the chart: the context menu (a
 * right-click, Shift+F10), the sign-in link when signed out, the plan editor,
 * and the visible-range volume profile with its badges.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChartWithTools } from "@/components/chart-tools";
import { priceAlertFields } from "@/lib/chart-menu";

import { panChart, resetLwc } from "../stubs/lightweight-charts";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "dark" }) }));
vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);

const nav = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.search),
  usePathname: () => "/stocks/AAPL",
}));

const alerts = vi.hoisted(() => ({ createAlertAction: vi.fn(async () => ({ createdId: 1 })) }));
vi.mock("@/app/(product)/(authed)/alerts/actions", () => alerts);
const tools = vi.hoisted(() => ({
  volumeProfileAction: vi.fn(),
  chartRuleSetupAction: vi.fn(),
  chartPlansAction: vi.fn(async () => ({ plans: [] })),
  createChartPlanAction: vi.fn(),
  updatePlanLinesAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/chart-tools-actions", () => tools);
vi.mock("@/app/(product)/stocks/[ticker]/drawing-actions", () => ({
  createDrawingAction: vi.fn(),
  updateDrawingAction: vi.fn(),
  deleteDrawingAction: vi.fn(),
}));
vi.mock("@/app/(product)/stocks/[ticker]/avwap-actions", () => ({
  avwapAction: vi.fn(async () => ({ error: "not in this test" })),
  lastEarningsDateAction: vi.fn(async () => ({ date: null })),
}));

const BARS = [
  { ts: "2025-04-01T00:00:00", open: "100", high: "101", low: "99", close: "100", volume: 10 },
  { ts: "2025-04-02T00:00:00", open: "100", high: "102", low: "99", close: "101", volume: 10 },
];
const INITIAL = {
  ticker: "AAPL",
  drawings: [],
  limit: 200,
  first_bar: "2025-04-01",
  last_bar: "2025-04-02",
};

function renderTools(props: Partial<Parameters<typeof ChartWithTools>[0]> = {}) {
  return render(
    <ChartWithTools
      ticker="AAPL"
      signedIn
      initial={INITIAL}
      callbackUrl="/stocks/AAPL"
      bars={BARS}
      {...props}
    />,
  );
}

/** A right-click in the price pane: the stub's pane is 100 px tall, price = 200 - y. */
function rightClick(y = 50) {
  fireEvent.contextMenu(screen.getByTestId("price-chart"), { clientX: 0, clientY: y });
}

describe("the chart's context menu (A6.7)", () => {
  beforeEach(() => {
    resetLwc();
    nav.search = "";
    alerts.createAlertAction.mockClear();
    tools.volumeProfileAction.mockReset();
  });

  it("opens on a right-click with the four actions and the judging note", () => {
    renderTools();
    rightClick();
    const menu = screen.getByTestId("chart-context-menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((i) => i.dataset.item),
    ).toEqual(["price", "drawing", "indicator", "plan"]);
    expect(within(menu).getAllByRole("menuitem")[0]).toHaveFocus();
    expect(screen.getByTestId("chart-menu-note")).toHaveTextContent("next stored bar");
    // No drawing or study under the pointer: those two say why.
    expect(menu.querySelector('[data-item="drawing"]')).toHaveAttribute("data-disabled", "true");
    expect(menu.querySelector('[data-item="indicator"]')).toHaveAttribute("data-disabled", "true");
  });

  it("sets the price alert through the alert form's action, with its fields", async () => {
    renderTools();
    rightClick(50);
    fireEvent.click(screen.getByRole("menuitem", { name: /Alert When Price Crosses Here/ }));
    await waitFor(() => expect(alerts.createAlertAction).toHaveBeenCalledTimes(1));
    const form = (alerts.createAlertAction.mock.calls[0] as unknown[])[1] as FormData;
    expect(Object.fromEntries(form.entries())).toEqual(priceAlertFields("AAPL", 150, 101));
    expect(await screen.findByTestId("chart-tools-message")).toHaveTextContent(
      "Alert set. When AAPL closes above 150.00, once.",
    );
    expect(screen.queryByTestId("chart-context-menu")).toBeNull();
  });

  it("opens from the keyboard (Shift+F10) and closes with Escape", () => {
    renderTools();
    const chart = screen.getByTestId("price-chart");
    fireEvent.keyDown(chart, { key: "F10", shiftKey: true });
    const menu = screen.getByTestId("chart-context-menu");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(within(menu).getAllByRole("menuitem")[1]).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByTestId("chart-context-menu")).toBeNull();
    expect(chart).toHaveFocus();
  });

  it("signed out, offers a sign-in link instead", () => {
    renderTools({ signedIn: false, initial: null });
    rightClick();
    const link = screen.getByRole("menuitem", { name: /Sign in to set alerts/ });
    expect(link).toHaveAttribute("href", "/login?callbackUrl=%2Fstocks%2FAAPL");
  });

  it("opens the plan editor with the entry at the crosshair", () => {
    renderTools();
    rightClick(50);
    fireEvent.click(screen.getByRole("menuitem", { name: /Plan a Trade Here/ }));
    const editor = screen.getByTestId("chart-plan-editor");
    expect(within(editor).getByLabelText("Entry")).toHaveValue("150.00");
    // No drawings: the stop is 2 x ATR below and the target 2R above.
    expect(editor).toHaveTextContent("Stop 2 × ATR(14) below the entry.");
  });
});

describe("the visible-range volume profile (A6.7)", () => {
  beforeEach(() => {
    resetLwc();
    tools.volumeProfileAction.mockReset();
  });

  it("fetches the bars on screen, debounced, and shows the badges", async () => {
    nav.search = "vp=visible";
    tools.volumeProfileAction.mockResolvedValue({
      profile: {
        ticker: "AAPL",
        source: "daily",
        feed: null,
        from: "2025-04-01T00:00:00",
        to: "2025-04-02T23:59:59",
        bars: 2,
        bins: [{ low: "99", high: "102", volume: 20 }],
        poc: "100.5",
        poc_index: 0,
        vah: "102",
        val: "99",
        value_area: 0.7,
        total_volume: 20,
        value_volume: 20,
        badges: ["EOD approximation"],
        note: "Minute bars do not cover the whole range.",
      },
    });
    renderTools();
    panChart();
    panChart();
    await waitFor(() => expect(tools.volumeProfileAction).toHaveBeenCalled(), { timeout: 2000 });
    expect(tools.volumeProfileAction).toHaveBeenCalledTimes(1);
    expect(tools.volumeProfileAction).toHaveBeenCalledWith("AAPL", {
      from: "2025-04-01T00:00:00Z",
      to: "2025-04-02T23:59:59Z",
      bins: 24,
    });
    expect(await screen.findByTestId("volume-profile-badge")).toHaveTextContent(
      "EOD approximation",
    );
    expect(screen.getByTestId("volume-profile-caption")).toHaveTextContent(
      "POC 100.5, value area (70%) 99 to 102.",
    );
  });

  it("offers no profile on an index", async () => {
    nav.search = "vp=visible";
    renderTools({ isIndex: true });
    panChart();
    await new Promise((r) => setTimeout(r, 500));
    expect(tools.volumeProfileAction).not.toHaveBeenCalled();
    expect(screen.getByTestId("chart-tools")).toHaveAttribute("data-profile-mode", "off");
  });
});
