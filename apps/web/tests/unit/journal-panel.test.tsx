import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JournalPanel } from "@/components/journal/journal-panel";
import type { JournalDay, JournalMonth, JournalStats } from "@/lib/api/journal";

// The panel reads Journal state straight out of the URL, so the mock stands in
// for the contract App Router gives `useSearchParams` when the native History
// API is used: `pushState` updates the params *and* re-renders the subscriber.
let search = "?tab=journal&month=2026-08";
const subscribers = new Set<() => void>();

function pushSearch(next: string) {
  search = next;
  for (const notify of [...subscribers]) notify();
}

vi.mock("next/navigation", async () => {
  const { useEffect, useReducer } = await import("react");
  return {
    useSearchParams: () => {
      const [, rerender] = useReducer((count: number) => count + 1, 0);
      useEffect(() => {
        subscribers.add(rerender);
        return () => {
          subscribers.delete(rerender);
        };
      }, []);
      return new URLSearchParams(search);
    },
  };
});

function stats(realized: string, tradeCount: number, extra: Partial<JournalStats> = {}) {
  return {
    realized_pnl: realized,
    trade_count: tradeCount,
    winning_trades: Number(realized) > 0 ? tradeCount : 0,
    losing_trades: Number(realized) < 0 ? tradeCount : 0,
    gross_profit: Number(realized) > 0 ? realized : "0",
    gross_loss: Number(realized) < 0 ? String(-Number(realized)) : "0",
    win_rate: Number(realized) > 0 ? 1 : 0,
    profit_factor: null,
    ...extra,
  } satisfies JournalStats;
}

const august: JournalMonth = {
  unavailable_count: 0,
  period: { year: 2026, month: 8, first_day: "2026-08-01", last_day: "2026-08-31" },
  currency: "USD",
  summary: stats("18683.12", 143, { win_rate: 0.6713 }),
  return_pct: 18.7,
  start_nav: "100000",
  days: [
    { date: "2026-08-19", stats: stats("5267.00", 20, { win_rate: 0.7 }) },
    { date: "2026-08-20", stats: stats("-412.50", 4, { win_rate: 0.25 }) },
  ],
  weeks: [
    { start: "2026-08-01", end: "2026-08-02", stats: stats("0", 0, { win_rate: null }) },
    { start: "2026-08-17", end: "2026-08-23", stats: stats("6754.30", 63, { win_rate: 0.6 }) },
  ],
};

const emptyAugust: JournalMonth = {
  ...august,
  summary: stats("0", 0, { win_rate: null }),
  return_pct: null,
  days: [],
  weeks: [{ start: "2026-08-01", end: "2026-08-02", stats: stats("0", 0, { win_rate: null }) }],
};

const august19: JournalDay = {
  unavailable_count: 0,
  offset: 0,
  has_more: false,
  date: "2026-08-19",
  currency: "USD",
  stats: stats("5267.00", 2, { win_rate: 0.5 }),
  executions: [
    {
      kind: "equity",
      reference_id: 11,
      ticker: "AAPL",
      session_date: "2026-08-19",
      executed_at: "2026-08-19T18:00:00",
      realized_pnl: "272.00",
      currency: "USD",
      side: "sell",
      quantity: "100",
      price: "229.12",
      avg_cost: "226.40",
      option_type: null,
      strike: null,
      expiry: null,
      contracts: null,
      premium_paid: null,
      proceeds: null,
      option_status: null,
      signal_at_entry: { score: 5, max_score: 7, computed_at: "2026-08-18T21:00:00" },
    },
    {
      kind: "option",
      reference_id: 4,
      ticker: "TSLA",
      session_date: "2026-08-19",
      executed_at: "2026-08-19T19:00:00",
      realized_pnl: "4995.00",
      currency: "USD",
      side: null,
      quantity: null,
      price: null,
      avg_cost: null,
      option_type: "call",
      strike: "250.00",
      expiry: "2026-09-18",
      contracts: 2,
      premium_paid: "400.00",
      proceeds: "5395.00",
      option_status: "closed",
      signal_at_entry: null,
    },
  ],
};

function mockFetch(handler: (url: string) => { ok: boolean; body?: unknown; status?: number }) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const result = handler(url);
    return {
      ok: result.ok,
      status: result.status ?? (result.ok ? 200 : 500),
      json: async () => result.body,
    } as Response;
  });
}

function renderPanel(month: JournalMonth | null = august, failed = false) {
  return render(
    <JournalPanel initialMonthKey="2026-08" initialMonth={month} initialError={failed} />,
  );
}

describe("trading journal panel", () => {
  it("moves Home and End within the actual Monday-first calendar row", async () => {
    const user = userEvent.setup();
    renderPanel();
    screen.getByTestId("journal-day-2026-08-19").focus();
    await user.keyboard("{Home}");
    expect(screen.getByTestId("journal-day-2026-08-17")).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByTestId("journal-day-2026-08-23")).toHaveFocus();
  });

  it("ignores a late day response after selecting another day", async () => {
    const user = userEvent.setup();
    const pending = new Map<string, (value: Response) => void>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => new Promise<Response>((resolve) => pending.set(url, resolve))),
    );
    renderPanel();
    await user.click(screen.getByTestId("journal-day-2026-08-19"));
    await user.click(screen.getByTestId("journal-day-2026-08-20"));
    const later = {
      ...august19,
      date: "2026-08-20",
      executions: [{ ...august19.executions[0], ticker: "MSFT" }],
    };
    await act(async () =>
      pending.get("/api/journal/days/2026-08-20")?.({
        ok: true,
        json: async () => later,
      } as Response),
    );
    await act(async () =>
      pending.get("/api/journal/days/2026-08-19")?.({
        ok: true,
        json: async () => august19,
      } as Response),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("MSFT")).toBeVisible();
    expect(within(dialog).queryByText("AAPL")).not.toBeInTheDocument();
  });
  it("can revisit a month whose request was cancelled", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    renderPanel();
    await user.click(screen.getByRole("button", { name: "Previous month" }));
    await user.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByText("+$18,683.12")).toBeVisible();
    const july = {
      ...emptyAugust,
      period: { year: 2026, month: 7, first_day: "2026-07-01", last_day: "2026-07-31" },
    };
    vi.stubGlobal(
      "fetch",
      mockFetch(() => ({ ok: true, body: july })),
    );
    await user.click(screen.getByRole("button", { name: "Previous month" }));
    await waitFor(() => expect(screen.getByText("No closed trades this month.")).toBeVisible());
  });

  it("ignores an impossible or out-of-month inspector URL", () => {
    search = "?tab=journal&month=2026-08&date=2026-09-01";
    renderPanel();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("restores a selected day on history navigation and closes with Escape", async () => {
    const user = userEvent.setup();
    renderPanel();
    act(() => pushSearch("?tab=journal&month=2026-08&date=2026-08-19"));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("formats ledger gains in USD while retaining native entry and exit prices", async () => {
    const user = userEvent.setup();
    const foreign = { ...august19, executions: [{ ...august19.executions[0], currency: "EUR" }] };
    vi.stubGlobal(
      "fetch",
      mockFetch(() => ({ ok: true, body: foreign })),
    );
    renderPanel();
    await user.click(screen.getByTestId("journal-day-2026-08-19"));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("+$272.00")).toBeVisible());
    expect(within(dialog).getByText("€229.12")).toBeVisible();
  });
  beforeEach(() => {
    subscribers.clear();
    search = "?tab=journal&month=2026-08";
    vi.stubGlobal(
      "fetch",
      mockFetch((url) =>
        url.includes("/days/2026-08-19")
          ? { ok: true, body: august19 }
          : { ok: true, body: august },
      ),
    );
    // Radix Dialog needs these in jsdom.
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.spyOn(window.history, "pushState").mockImplementation((_state, _title, url) => {
      pushSearch(String(url).slice(String(url).indexOf("?")));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows the month's headline figures from server-rendered data", () => {
    renderPanel();

    expect(screen.getByText("Realized P&L · USD")).toBeVisible();
    expect(screen.getByText("+$18,683.12")).toBeVisible();
    expect(screen.getByText("+18.70%")).toBeVisible();
    expect(screen.getByText("143")).toBeVisible();
    expect(screen.getByText("67%")).toBeVisible();
  });

  it("describes each day in words so the tint is never the only signal", () => {
    renderPanel();

    expect(
      screen.getByRole("button", { name: "August 19, profit 5,267.00 dollars, 20 trades" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "August 20, loss 412.50 dollars, 4 trades" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "August 18, no closed trades" })).toBeVisible();
  });

  it("tints a profitable day and a losing day differently, and leaves quiet days untinted", () => {
    renderPanel();

    const winner = screen.getByTestId("journal-day-2026-08-19");
    const loser = screen.getByTestId("journal-day-2026-08-20");
    const quiet = screen.getByTestId("journal-day-2026-08-18");

    expect(winner).toHaveAttribute("data-sign", "positive");
    expect(loser).toHaveAttribute("data-sign", "negative");
    expect(quiet).toHaveAttribute("data-sign", "flat");
    expect(quiet).toHaveAttribute("data-level", "0");
  });

  it("opens the inspector on a day and lists that day's real executions", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByTestId("journal-day-2026-08-19"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("AAPL")).toBeVisible());

    expect(within(dialog).getByRole("heading", { name: "August 19, 2026" })).toBeVisible();
    expect(within(dialog).getByText("+$272.00")).toBeVisible();
    expect(within(dialog).getByText("5 / 7 votes")).toBeVisible();
    // The option leg keeps option nomenclature rather than borrowing the
    // equity fields.
    expect(within(dialog).getByText(/LONG CALL 250\.00/)).toBeVisible();
    expect(within(dialog).getByText("Premium paid")).toBeVisible();
  });

  it("puts the open day in the URL so the view is shareable", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByTestId("journal-day-2026-08-19"));

    expect(window.history.pushState).toHaveBeenCalled();
    expect(search).toContain("date=2026-08-19");
    expect(search).toContain("month=2026-08");
  });

  it("navigates months through the URL without dropping the open selection state", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Previous month" }));

    expect(search).toContain("month=2026-07");
    expect(search).not.toContain("date=");
  });

  it("opens the week inspector with the week's own aggregate", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetch(() => ({
        ok: true,
        body: {
          ...august.weeks[1],
          currency: "USD",
          best_trade: august19.executions[1],
          worst_trade: august19.executions[0],
        },
      })),
    );
    renderPanel();

    await user.click(screen.getByTestId("journal-week-2026-08-17"));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: /Week of Aug 17 – Aug 23, 2026/ }),
    ).toBeVisible();
    expect(within(dialog).getByText("+$6,754.30")).toBeVisible();
    expect(within(dialog).getAllByText("63").length).toBeGreaterThan(0);
    expect(within(dialog).getByText("Profit factor")).toBeVisible();
    await waitFor(() => expect(within(dialog).getByText("Best trade")).toBeVisible());
    expect(within(dialog).getByText("Worst trade")).toBeVisible();
  });

  it("loads more executions without replacing full-day totals", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => ({
        ok: true,
        body: url.includes("offset=1")
          ? { ...august19, executions: [august19.executions[1]], has_more: false, offset: 1 }
          : { ...august19, executions: [august19.executions[0]], has_more: true, offset: 0 },
      })),
    );
    renderPanel();
    await user.click(screen.getByTestId("journal-day-2026-08-19"));
    await user.click(await screen.findByRole("button", { name: "Load more trades" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("TSLA")).toBeVisible());
    expect(within(dialog).getByText("AAPL")).toBeVisible();
    expect(within(dialog).getByText("+$5,267.00")).toBeVisible();
  });

  it("discloses missing historical accounting instead of claiming an empty month", () => {
    renderPanel({ ...emptyAugust, unavailable_count: 2 });
    expect(screen.getByText(/2 historical closing records/)).toBeVisible();
    expect(screen.queryByText("No closed trades this month.")).not.toBeInTheDocument();
  });

  it("frames an inactive month as quiet rather than as a problem", () => {
    renderPanel(emptyAugust);

    expect(screen.getByText("No closed trades this month.")).toBeVisible();
    expect(
      screen.getByText(
        "Your realized trading activity will appear here after positions are closed.",
      ),
    ).toBeVisible();
    // The percentage has no valid denominator here, so it is hidden.
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("keeps the calendar intact when a day's detail fails", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      mockFetch((url) =>
        url.includes("/days/") ? { ok: false, status: 503 } : { ok: true, body: august },
      ),
    );
    renderPanel();

    await user.click(screen.getByTestId("journal-day-2026-08-19"));

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("Couldn't load this day.")).toBeVisible());
    expect(within(dialog).getByRole("button", { name: "Try again" })).toBeVisible();
    // The month behind the inspector is untouched.
    expect(screen.getByText("+$18,683.12")).toBeVisible();
  });

  it("offers a scoped retry when the month itself never arrived", async () => {
    const user = userEvent.setup();
    renderPanel(null, true);

    expect(screen.getByText("Couldn't load the journal.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(screen.getByText("+$18,683.12")).toBeVisible());
  });
});
