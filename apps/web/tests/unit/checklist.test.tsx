import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Checklist, ChecklistDimension, ChecklistRow } from "@/lib/api/types";
import {
  buildChecklistHref,
  filterChecklistRows,
  parseDimension,
  parseMinMet,
  variantFor,
} from "@/lib/checklist-view";

const universe = {
  name: "pinned",
  point_in_time: false,
  survivorship_biased: true,
  note: "Graded on the pinned symbol list with today's provider history.",
};

function dimension(key: string, name: string, rule: string, grade?: "A" | "D"): ChecklistDimension {
  return {
    key,
    name,
    summary: `${name} summary.`,
    source: `${name} source.`,
    variants: [
      {
        scope: "all",
        setup_id: 1,
        setup_version_id: key.length,
        version: 1,
        canonical: rule,
        hash: "h",
        conditions: [{ label: `${name} condition`, rule }],
        evidence: grade
          ? {
              grade,
              n_events: 352,
              symbols: 25,
              horizon: 20,
              window_start: "2016-11-26",
              window_end: "2026-11-24",
              mean_excess: 0.0123,
              t_stat: 3.4,
              hit_rate: 0.56,
              overlapping_skipped: 4,
              universe,
              computed_at: "2026-11-25T22:00:00",
            }
          : null,
      },
    ],
  };
}

const DIMENSIONS: ChecklistDimension[] = [
  dimension("trend", "Trend", "close > sma(close, 200)", "A"),
  dimension("momentum", "Momentum / relative strength", "rs(126) > 0"),
  {
    ...dimension("volume", "Volume / delivery", "volume > sma(volume, 50)", "D"),
    variants: [
      {
        ...dimension("volume", "x", "(delivery_pct > 50) and (volume > sma(volume, 50))")
          .variants[0],
        scope: "india",
        setup_version_id: 70,
      },
      {
        ...dimension("volume", "x", "volume > sma(volume, 50)", "D").variants[0],
        scope: "other",
        setup_version_id: 71,
      },
    ],
  },
  dimension("regime", "Market regime", "index_close > sma(index_close, 200)"),
  dimension("quality", "Quality", "fundamental.roe > 15"),
  dimension("risk", "Risk / reward", "atr(14) < 0.04 * close"),
];

function row(ticker: string, statuses: string[], name = `${ticker} Inc.`): ChecklistRow {
  const met = statuses.filter((s) => s === "met").length;
  const evaluated = statuses.filter((s) => s !== "unknown").length;
  return {
    ticker,
    name,
    session_date: "2025-04-07",
    met,
    evaluated,
    total: 6,
    computed_at: "2025-04-07T22:00:00",
    stale: false,
    results: DIMENSIONS.map((d, i) => ({
      key: d.key,
      scope: d.key === "volume" ? "other" : "all",
      setup_version_id: d.key === "volume" ? 71 : d.variants[0].setup_version_id,
      status: statuses[i] as "met" | "not_met" | "unknown",
      reason: statuses[i] === "unknown" ? "index_close: no ^GSPC close" : null,
      conditions: [
        {
          label: `${d.name} condition`,
          rule: d.variants[0].conditions[0].rule,
          status: statuses[i] as "met" | "not_met" | "unknown",
          reason: statuses[i] === "unknown" ? "index_close: no ^GSPC close" : null,
        },
      ],
    })),
  };
}

const CHECKLIST: Checklist = {
  dimensions: DIMENSIONS,
  rows: [
    row("MSFT", ["not_met", "not_met", "met", "unknown", "unknown", "met"], "Microsoft"),
    row("V", ["met", "not_met", "met", "unknown", "unknown", "met"], "Visa"),
    row("AAPL", ["met", "met", "met", "unknown", "unknown", "met"], "Apple"),
  ],
  total: 3,
  universe,
  disclaimer:
    "The Checklist counts how many of six published conditions a symbol meets. It is not a recommendation.",
};

const getChecklist = vi.fn(async () => CHECKLIST);
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getChecklist: () => getChecklist() };
});
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/checklist",
  permanentRedirect: vi.fn(),
}));

import ChecklistPage from "@/app/(product)/checklist/page";
import { ChecklistPanel } from "@/components/checklist/checklist-panel";

const FORBIDDEN = /\b(buy|sell|bullish|bearish|strong buy|signal)\b/i;

describe("checklist view helpers", () => {
  it("parses URL state and builds shareable links", () => {
    expect(parseMinMet("9")).toBe(6);
    expect(parseMinMet("x")).toBe(0);
    expect(parseDimension("TREND", ["trend"])).toBe("trend");
    expect(parseDimension("nope", ["trend"])).toBeUndefined();
    expect(buildChecklistHref({})).toBe("/checklist");
    expect(buildChecklistHref({ min: 4, dimension: "trend", sort: "ticker", q: "AAPL" })).toBe(
      "/checklist?min=4&dimension=trend&sort=ticker&q=AAPL",
    );
  });

  it("sorts most met first, then by ticker, and searches names", () => {
    expect(filterChecklistRows(CHECKLIST.rows, { sort: "met" }).map((r) => r.ticker)).toEqual([
      "AAPL",
      "V",
      "MSFT",
    ]);
    expect(filterChecklistRows(CHECKLIST.rows, { sort: "ticker" }).map((r) => r.ticker)).toEqual([
      "AAPL",
      "MSFT",
      "V",
    ]);
    expect(
      filterChecklistRows(CHECKLIST.rows, { sort: "met", query: "micro" }).map((r) => r.ticker),
    ).toEqual(["MSFT"]);
  });

  it("picks the dimension setup that judged the symbol (delivery is India only)", () => {
    const volume = DIMENSIONS[2];
    expect(variantFor(volume, { scope: "other", setup_version_id: 71 })?.scope).toBe("other");
    expect(variantFor(volume, { scope: "india", setup_version_id: null })?.scope).toBe("india");
  });
});

describe("/checklist page", () => {
  it("lists symbols most met first with each dimension's status in words", async () => {
    render(await ChecklistPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("heading", { name: "Checklist" })).toBeVisible();
    const rows = screen.getAllByTestId(/^checklist-row-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual([
      "checklist-row-AAPL",
      "checklist-row-V",
      "checklist-row-MSFT",
    ]);
    const aapl = within(rows[0]);
    expect(aapl.getByText(/4 of 6 met/)).toBeInTheDocument();
    expect(aapl.getByText(/4 judged, 2 unknown/)).toBeInTheDocument();
    const statuses = within(aapl.getByRole("list", { name: "AAPL dimensions" }));
    expect(statuses.getAllByText("Met")).toHaveLength(4);
    expect(statuses.getAllByText("Unknown")).toHaveLength(2);
    expect(screen.getByTestId("checklist-disclaimer")).toHaveTextContent(/not a recommendation/);
  });

  it("filters by minimum met and by a dimension that must be met, and sorts by ticker", async () => {
    const { unmount } = render(
      await ChecklistPage({ searchParams: Promise.resolve({ min: "4" }) }),
    );
    expect(screen.getAllByTestId(/^checklist-row-/)).toHaveLength(1);
    unmount();
    const second = render(
      await ChecklistPage({
        searchParams: Promise.resolve({ dimension: "trend", sort: "ticker" }),
      }),
    );
    expect(screen.getAllByTestId(/^checklist-row-/).map((r) => r.dataset.testid)).toEqual([
      "checklist-row-AAPL",
      "checklist-row-V",
    ]);
    expect(screen.getByRole("link", { name: "At least 3 of 6" })).toHaveAttribute(
      "href",
      "/checklist?min=3&dimension=trend&sort=ticker",
    );
    second.unmount();
  });

  it("expands a symbol to its formulas, grade, sample and survivorship note", async () => {
    render(await ChecklistPage({ searchParams: Promise.resolve({ q: "AAPL" }) }));
    const card = screen.getByTestId("checklist-row-AAPL") as HTMLDetailsElement;
    expect(card.open).toBe(true); // an exact ticker search opens its card
    const detail = within(card);
    expect(detail.getAllByText("close > sma(close, 200)").length).toBeGreaterThan(0);
    expect(detail.getAllByText("Grade A").length).toBeGreaterThan(0);
    expect(
      detail.getAllByText(/352 events over 25 symbols, 2016-11-26 to 2026-11-24/).length,
    ).toBeGreaterThan(0);
    expect(detail.getAllByTestId("evidence-universe")[0]).toHaveTextContent(/survivorship-biased/);
    expect(detail.getAllByText("index_close: no ^GSPC close").length).toBeGreaterThan(0);
    // Volume is judged by the "outside India" setup for a US listing.
    expect(detail.getAllByText("Grade D").length).toBeGreaterThan(0);
  });

  it("explains each dimension with its source and never uses buy or sell words", async () => {
    const { container } = render(await ChecklistPage({ searchParams: Promise.resolve({}) }));
    const guide = screen.getByTestId("dimension-volume");
    fireEvent.click(within(guide).getByText("Volume / delivery"));
    expect(within(guide).getByText("NSE and BSE Listings · Version 1")).toBeInTheDocument();
    expect(
      within(guide).getByText(
        "Not graded yet: the weekly evidence study has not run on this formula.",
      ),
    ).toBeInTheDocument();
    expect(container.textContent ?? "").not.toMatch(FORBIDDEN);
  });
});

describe("ChecklistPanel (stock page)", () => {
  it("shows the six dimensions compactly with the count and session", () => {
    const aapl = CHECKLIST.rows[2];
    render(
      <ChecklistPanel
        checklist={{
          ticker: "AAPL",
          dimensions: DIMENSIONS,
          row: aapl,
          universe,
          disclaimer: CHECKLIST.disclaimer,
        }}
      />,
    );
    const panel = screen.getByTestId("stock-checklist");
    expect(
      within(panel).getByText(/4 of 6 met · 4 judged, 2 unknown · session 2025-04-07/),
    ).toBeVisible();
    expect(within(panel).getAllByRole("listitem")).toHaveLength(6);
    expect(within(panel).getByRole("link", { name: "Formulas and evidence" })).toHaveAttribute(
      "href",
      "/checklist?q=AAPL",
    );
    expect(panel.textContent ?? "").not.toMatch(FORBIDDEN);
  });

  it("says when the symbol has not been scored yet", () => {
    render(
      <ChecklistPanel
        checklist={{ ticker: "TSLA", dimensions: DIMENSIONS, row: null, universe, disclaimer: "" }}
      />,
    );
    expect(screen.getByText(/Not scored yet/)).toBeVisible();
  });
});
