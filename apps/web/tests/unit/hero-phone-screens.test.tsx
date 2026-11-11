import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const loadPanel = vi.fn();
const getNewsForTicker = vi.fn();

vi.mock("@/components/marketing/hero-panel", () => ({
  loadPanel: () => loadPanel(),
}));
vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {},
  getNewsForTicker: (...args: unknown[]) => getNewsForTicker(...args),
}));

const { loadPhoneScreens } = await import("@/components/marketing/hero-phone-screens");

const panel = {
  ticker: "NVDA",
  name: "NVIDIA Corporation",
  currency: "USD",
  bars: [
    { ts: "2025-04-02T00:00:00", open: "90", high: "96", low: "89", close: "94.31", volume: 1 },
    { ts: "2025-04-03T00:00:00", open: "94", high: "99", low: "93", close: "97.64", volume: 1 },
  ],
};

describe("loadPhoneScreens", () => {
  beforeEach(() => {
    loadPanel.mockReset();
    getNewsForTicker.mockReset();
  });

  it("puts the example portfolio first and labels it as an example", async () => {
    loadPanel.mockResolvedValue(null);
    const screens = await loadPhoneScreens();

    expect(screens.map((s) => s.key)).toEqual(["portfolio"]);
    render(<div>{screens[0].node}</div>);
    expect(screen.getByText("EXAMPLE ACCOUNT")).toBeVisible();
  });

  it("dates the stock and review screens by the real stored close", async () => {
    loadPanel.mockResolvedValue(panel);
    getNewsForTicker.mockResolvedValue([]);
    const screens = await loadPhoneScreens();

    // No stored headlines: the news screen is left out, not shown empty.
    expect(screens.map((s) => s.key)).toEqual(["portfolio", "stock", "review"]);
    render(<div>{screens[2].node}</div>);
    expect(screen.getByText("$97.64 · Apr 3, 2025")).toBeVisible();
    expect(screen.getByText("None in the simulator")).toBeVisible();
  });

  it("shows stored headlines with their source and no verification claim", async () => {
    loadPanel.mockResolvedValue(panel);
    getNewsForTicker.mockResolvedValue([
      {
        id: "doc_1",
        tickers: ["NVDA"],
        title: "Chip maker reports record quarter",
        url: "https://example.com/a",
        source: "Reuters",
        published_at: null,
        available_at: "2025-04-04T02:00:00",
        sentiment: null,
        sentiment_model: null,
        topic: null,
      },
    ]);
    const screens = await loadPhoneScreens();

    expect(screens.at(-1)?.key).toBe("news");
    render(<div>{screens.at(-1)?.node}</div>);
    expect(screen.getByText("Reuters")).toBeVisible();
    // No publisher time (GDELT): dated by when Aegis had it (audit AG-12).
    expect(screen.getByText("Apr 4, 2025")).toBeVisible();
    expect(screen.queryByText(/verified/i)).not.toBeInTheDocument();
  });
});
