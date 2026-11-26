import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { eventSummary, formatR } from "@/lib/chart-events";
import {
  type JournalEntry,
  type JournalEntrySummary,
  entryHref,
  entryPlanBadge,
  excursionPct,
  placeExcursionMarkers,
  rText,
  splitEntryTags,
} from "@/lib/journal-entries";

import { lwcCalls, resetLwc } from "../stubs/lightweight-charts";

vi.mock("lightweight-charts", async () => (await import("../stubs/lightweight-charts")).lwc);
vi.mock("@/app/(product)/(authed)/portfolio/journal-actions", () => ({
  saveEntryReviewAction: vi.fn(async () => ({ ok: "Review saved" })),
}));

const { JournalEntriesPanel } = await import("@/components/journal/journal-entries-panel");
const { JournalEntryChart } = await import("@/components/journal/journal-entry-chart");
const { PriceChart } = await import("@/components/price-chart");

function summary(overrides: Partial<JournalEntrySummary> = {}): JournalEntrySummary {
  return {
    id: 7,
    source: "imported",
    book_id: 3,
    replay_session_id: null,
    ticker: "RELIANCE.NS",
    currency: "INR",
    venue: "XNSE",
    side: "long",
    status: "closed",
    opened_at: "2025-05-05T04:00:00",
    closed_at: "2025-05-08T04:45:00",
    entry_date: "2025-05-05",
    exit_date: "2025-05-08",
    as_of_date: null,
    mark_close: null,
    avg_entry: "1200.000000",
    avg_exit: "1300.000000",
    quantity: "10.000000",
    held: "0",
    net_pnl: "968.500000",
    realized_pnl: "1000.000000",
    unrealized_pnl: null,
    fees: "31.500000",
    fees_estimated: true,
    return_pct: "8.0708",
    holding_days: 3,
    holding_sessions: 4,
    fills_count: 2,
    r_multiple: 0.9685,
    r_reason: null,
    initial_risk: "1000.000000",
    excursions: {
      basis: "approximate_daily",
      note: "Daily bars: may include moves before entry or after exit.",
      mae: {
        per_share: "-30.000000",
        pct: "-2.5000",
        amount: "-300.000000",
        shares: "10",
        date: "2025-05-07",
        price: "1170",
        r: -0.3,
      },
      mfe: {
        per_share: "110.000000",
        pct: "9.1667",
        amount: "1100.000000",
        shares: "10",
        date: "2025-05-08",
        price: "1310",
        r: 1.1,
      },
      reason: null,
      missing_sessions: [],
      sessions: 4,
    },
    plan: {
      id: 2,
      status: "closed",
      label: "locked",
      locked_at: "2025-05-05T04:00:00",
      first_fill_at: "2025-05-05T04:00:00",
      planned_entry: "1200.000000",
      planned_stop: "1100.000000",
      planned_target: "1400.000000",
      planned_size: "10.000000",
      setup_version_id: null,
      setup_label: null,
      counts_for_adherence: true,
    },
    setup_tags: [],
    mistake_tags: [],
    has_notes: false,
    ...overrides,
  };
}

function detail(overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    ...summary(),
    fills: [
      {
        trade_id: 1,
        replay_fill_id: null,
        side: "buy",
        quantity: "10",
        price: "1200",
        fees: "15",
        fees_estimated: true,
        at: "2025-05-05T04:00:00",
        venue_date: "2025-05-05",
        time_known: true,
      },
      {
        trade_id: 2,
        replay_fill_id: null,
        side: "sell",
        quantity: "10",
        price: "1300",
        fees: "16.5",
        fees_estimated: true,
        at: "2025-05-08T04:45:00",
        venue_date: "2025-05-08",
        time_known: true,
      },
    ],
    adherence: null,
    adherence_note: null,
    news_at_entry: null,
    news_at_exit: null,
    review_notes: null,
    mistakes: null,
    lessons: null,
    updated_at: "2026-11-26T00:00:00",
    ...overrides,
  };
}

const BARS = ["05", "06", "07", "08"].map((d, i) => ({
  ts: `2025-05-${d}T00:00:00`,
  open: String(1200 + i * 10),
  high: String(1215 + i * 30),
  low: String(1185 - (i === 2 ? 15 : 0)),
  close: String(1210 + i * 30),
  volume: 1000,
}));

beforeEach(() => resetLwc());

describe("journal entry labels (A5.5)", () => {
  it("formats R, excursions and badges", () => {
    expect(formatR(1.25)).toBe("+1.25R");
    expect(formatR(-0.4)).toBe("-0.40R");
    expect(formatR(0)).toBe("0.00R");
    expect(rText(null)).toBe("—");
    expect(excursionPct(summary().excursions.mae)).toBe("-2.50%");
    expect(excursionPct(summary().excursions.mfe)).toBe("+9.17%");
    expect(entryPlanBadge(summary()).label).toBe("Locked plan");
    expect(entryPlanBadge(summary({ plan: null })).label).toBe("No plan");
    const base = summary().plan;
    if (!base) throw new Error("fixture has a plan");
    const after = summary({
      plan: { ...base, label: "written_after_entry", counts_for_adherence: false },
    });
    expect(entryPlanBadge(after)).toEqual({ label: "Written after entry", tone: "after" });
    expect(splitEntryTags(" a, ,b ")).toEqual(["a", "b"]);
    expect(entryHref(7, 3)).toBe("/portfolio/journal/7?book=3");
    expect(entryHref(7, null)).toBe("/portfolio/journal/7");
  });

  it("says a closing fill's R in the event summary", () => {
    const fill = {
      type: "fill" as const,
      date: "2025-05-08",
      ts: "2025-05-08T04:45:00",
      side: "sell",
      quantity: "10",
      price: "1300",
      r_multiple: 0.9685,
      closes_entry: true,
    };
    expect(eventSummary(fill)).toBe("Sold 10 at 1,300, closing the trade at +0.97R");
    expect(eventSummary({ ...fill, r_multiple: null })).toBe("Sold 10 at 1,300");
  });
});

describe("journal entries list (A5.5)", () => {
  it("lists entries with R, P&L, MAE, MFE and badges, and filters them", async () => {
    const open = summary({
      id: 8,
      status: "open",
      source: "paper",
      ticker: "AAPL",
      currency: "USD",
      exit_date: null,
      r_multiple: null,
      plan: null,
    });
    render(<JournalEntriesPanel entries={[open, summary()]} total={2} note={null} book={3} />);
    const rows = screen.getAllByTestId("journal-entry-row");
    expect(rows).toHaveLength(2);
    const closed = rows[1];
    expect(within(closed).getByTestId("entry-r")).toHaveTextContent("+0.97R");
    expect(within(closed).getByTestId("entry-mae")).toHaveTextContent("-2.50%");
    expect(within(closed).getByTestId("entry-mfe")).toHaveTextContent("+9.17%");
    expect(within(closed).getByTestId("entry-plan-badge")).toHaveTextContent("Locked plan");
    expect(within(closed).getByRole("link")).toHaveAttribute("href", "/portfolio/journal/7?book=3");
    expect(within(rows[0]).getByTestId("entry-plan-badge")).toHaveTextContent("No plan");
    expect(within(rows[0]).getByTestId("entry-r")).toHaveTextContent("—");

    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getAllByTestId("journal-entry-row")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.click(screen.getByRole("button", { name: "Imported" }));
    expect(screen.getAllByTestId("journal-entry-row")[0]).toHaveAttribute(
      "data-source",
      "imported",
    );
  });

  it("explains an empty or failed journal", () => {
    const { rerender } = render(
      <JournalEntriesPanel entries={[]} total={0} note={null} book={3} />,
    );
    expect(screen.getByText(/No round trips yet/)).toBeInTheDocument();
    rerender(<JournalEntriesPanel entries={null} total={0} note={null} book={3} />);
    expect(screen.getByText(/unavailable right now/)).toBeInTheDocument();
  });
});

describe("journal entry chart (A5.5)", () => {
  it("marks the fills with R on the closing fill, MAE and MFE, and the plan's lines", () => {
    render(<JournalEntryChart entry={detail()} bars={BARS} />);
    const markers = lwcCalls.markers.at(-1) as { text: string }[];
    const texts = markers.map((m) => m.text);
    expect(texts).toContain("B");
    expect(texts).toContain("S +0.97R");
    expect(texts).toContain("MAE -2.50%");
    expect(texts).toContain("MFE +9.17%");
    const price = lwcCalls.series.find((s) => s.priceLines.length) as { priceLines: number[] };
    expect(price.priceLines).toEqual([1200, 1100, 1400]);
  });

  it("says so when there are no bars", () => {
    render(<JournalEntryChart entry={detail()} bars={[]} />);
    expect(screen.getByText(/No stored bars/)).toBeInTheDocument();
  });

  it("keeps an opening fill's marker plain", () => {
    render(
      <PriceChart
        bars={BARS}
        events={[
          {
            type: "fill",
            date: "2025-05-05",
            ts: "2025-05-05T04:00:00",
            side: "buy",
            quantity: "10",
            price: "1200",
            r_multiple: null,
            closes_entry: false,
          },
        ]}
      />,
    );
    const markers = lwcCalls.markers.at(-1) as { text: string }[];
    expect(markers.map((m) => m.text)).toEqual(["B"]);
  });
});

describe("MAE / MFE marker placement (A5 fix)", () => {
  const fill = (side: "buy" | "sell", day: string, trade_id: number) => ({
    trade_id,
    replay_fill_id: null,
    side,
    quantity: "10",
    price: "1200",
    fees: "1",
    fees_estimated: true,
    at: `${day}T04:00:00`,
    venue_date: day,
    time_known: true,
  });
  const exc = (date: string, pct: string) => ({
    per_share: "1",
    pct,
    amount: "10",
    shares: "10",
    date,
    price: "1200",
    r: null,
  });

  it("keeps each excursion on its own side when the bar is free", () => {
    const entry = detail({
      fills: [fill("buy", "2025-05-05", 1), fill("sell", "2025-05-08", 2)],
      excursions: {
        ...detail().excursions,
        mae: exc("2025-05-06", "-1"),
        mfe: exc("2025-05-07", "2"),
      },
    });
    expect(placeExcursionMarkers(entry)).toEqual([
      { kind: "mae", date: "2025-05-06", position: "belowBar", mergeIntoFill: false },
      { kind: "mfe", date: "2025-05-07", position: "aboveBar", mergeIntoFill: false },
    ]);
  });

  it("moves MAE above the bar when the buy's B sits below it (the open entry case)", () => {
    const entry = detail({
      status: "open",
      fills: [fill("buy", "2025-05-05", 1)],
      excursions: {
        ...detail().excursions,
        mae: exc("2025-05-05", "-1.66"),
        mfe: exc("2025-05-08", "11"),
      },
    });
    const [mae, mfe] = placeExcursionMarkers(entry);
    expect(mae).toEqual({
      kind: "mae",
      date: "2025-05-05",
      position: "aboveBar",
      mergeIntoFill: false,
    });
    expect(mfe.position).toBe("aboveBar");
    render(<JournalEntryChart entry={entry} bars={BARS} />);
    const markers = lwcCalls.markers.at(-1) as { time: number; position: string; text: string }[];
    const day = markers.filter((m) => m.time === markers.find((x) => x.text === "B")?.time);
    // One marker per side of the bar: B below, MAE above; nothing stacks.
    expect(day.map((m) => [m.position, m.text])).toEqual([
      ["belowBar", "B"],
      ["aboveBar", "MAE -1.66%"],
    ]);
  });

  it("flips sides for a short and joins the fills' labels on an intraday round trip", () => {
    const entry = detail({
      side: "short",
      plan: null,
      r_multiple: null,
      fills: [fill("sell", "2025-05-05", 1), fill("buy", "2025-05-05", 2)],
      excursions: {
        ...detail().excursions,
        mae: exc("2025-05-05", "-0.4132"),
        mfe: exc("2025-05-05", "2.0661"),
      },
    });
    expect(placeExcursionMarkers(entry)).toEqual([
      { kind: "mae", date: "2025-05-05", position: "aboveBar", mergeIntoFill: true },
      { kind: "mfe", date: "2025-05-05", position: "belowBar", mergeIntoFill: true },
    ]);
    render(<JournalEntryChart entry={entry} bars={BARS} />);
    const markers = lwcCalls.markers.at(-1) as { position: string; text: string }[];
    expect(markers.map((m) => [m.position, m.text])).toEqual([
      ["aboveBar", "S · MAE -0.41%"],
      ["belowBar", "B · MFE +2.07%"],
    ]);
  });

  it("puts a short's MAE above a free bar and its MFE below", () => {
    const entry = detail({
      side: "short",
      fills: [fill("sell", "2025-05-05", 1), fill("buy", "2025-05-08", 2)],
      excursions: {
        ...detail().excursions,
        mae: exc("2025-05-06", "-1"),
        mfe: exc("2025-05-07", "2"),
      },
    });
    expect(placeExcursionMarkers(entry).map((p) => p.position)).toEqual(["aboveBar", "belowBar"]);
  });

  it("shows R on a closing buy (a short's cover)", () => {
    render(
      <PriceChart
        bars={BARS}
        events={[
          {
            type: "fill",
            date: "2025-05-05",
            ts: "2025-05-05T08:00:00",
            side: "buy",
            quantity: "10",
            price: "1200",
            r_multiple: 0.5,
            closes_entry: true,
          },
        ]}
      />,
    );
    const markers = lwcCalls.markers.at(-1) as { text: string }[];
    expect(markers.map((m) => m.text)).toEqual(["B +0.50R"]);
  });
});
