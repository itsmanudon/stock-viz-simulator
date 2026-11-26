import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/command-palette";
import type { Symbol as SymbolRow } from "@/lib/api/types";
import {
  OPEN_BOOK_SWITCHER_EVENT,
  RECENT_KEY,
  RECENT_LIMIT,
  buildCommands,
  filterCommands,
  pushRecent,
  readRecents,
  resolveCommandHref,
} from "@/lib/command-palette";

const push = vi.fn();
let pathname = "/markets";
let currentSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
  useSearchParams: () => currentSearchParams,
}));

function symbol(ticker: string, name: string): SymbolRow {
  return {
    ticker,
    name,
    sector: "Technology",
    exchange: "NASDAQ",
    currency: "USD",
    is_active: true,
  };
}

const TRIGGER = "Search tickers, pages and actions";

function openPalette() {
  fireEvent.click(screen.getByRole("button", { name: TRIGGER }));
  return within(screen.getByRole("dialog")).getByRole("combobox");
}

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
  };
}

describe("palette commands", () => {
  it("lists every sidebar page and the actions, hiding account-only ones from guests", () => {
    const signedIn = buildCommands({ signedIn: true }).map((c) => c.id);
    expect(signedIn).toEqual(
      expect.arrayContaining([
        "page:/screener",
        "page:/backtest/runs",
        "page:/copilot",
        "page:/settings",
        "action:new-backtest",
        "action:new-drill",
        "action:switch-book",
      ]),
    );
    const guest = buildCommands({ signedIn: false }).map((c) => c.id);
    expect(guest).not.toContain("page:/settings");
    expect(guest).not.toContain("action:switch-book");
    expect(guest).toContain("page:/status");
  });

  it("ranks a label that starts with the query first and needs every word to match", () => {
    const commands = buildCommands({ signedIn: true });
    expect(filterCommands(commands, "screen")[0].label).toBe("Screener");
    expect(filterCommands(commands, "new back")[0].id).toBe("action:new-backtest");
    expect(filterCommands(commands, "open screener").map((c) => c.id)).toContain("page:/screener");
    expect(filterCommands(commands, "drill deck")[0].id).toBe("action:new-drill");
    expect(filterCommands(commands, "switch book")[0].id).toBe("action:switch-book");
    // Workspace names match too.
    expect(filterCommands(commands, "quant").every((c) => c.workspaceId === "quant-lab")).toBe(
      true,
    );
    expect(filterCommands(commands, "new")[0].id).toBe("action:new-backtest");
    expect(filterCommands(commands, "zzqx")).toEqual([]);
    expect(filterCommands(commands, "a", 3)).toHaveLength(3);
  });

  it("carries the book onto book pages only", () => {
    expect(resolveCommandHref("/portfolio?tab=journal", 7)).toBe("/portfolio?tab=journal&book=7");
    expect(resolveCommandHref("/orders", "all")).toBe("/orders?book=all");
    expect(resolveCommandHref("/screener", 7)).toBe("/screener");
  });

  it("keeps recent picks newest first, deduplicated and capped, and survives bad storage", () => {
    const storage = memoryStorage();
    pushRecent(storage, { kind: "command", id: "page:/screener" });
    pushRecent(storage, { kind: "symbol", ticker: "AAPL", name: "Apple Inc." });
    pushRecent(storage, { kind: "command", id: "page:/screener" });
    expect(readRecents(storage).map((e) => (e.kind === "symbol" ? e.ticker : e.id))).toEqual([
      "page:/screener",
      "AAPL",
    ]);
    for (let i = 0; i < 10; i++) pushRecent(storage, { kind: "command", id: `x${i}` });
    expect(readRecents(storage)).toHaveLength(RECENT_LIMIT);

    expect(readRecents(memoryStorage({ [RECENT_KEY]: "{not json" }))).toEqual([]);
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readRecents(throwing)).toEqual([]);
    expect(() => pushRecent(throwing, { kind: "command", id: "a" })).not.toThrow();
  });
});

describe("CommandPalette", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
    pathname = "/markets";
    currentSearchParams = new URLSearchParams();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens with Ctrl+K and Cmd+K, closes with Escape and gives focus back", () => {
    render(<CommandPalette search={vi.fn()} debounceMs={20} />);
    const trigger = screen.getByRole("button", { name: TRIGGER });

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = within(screen.getByRole("dialog", { name: "Command palette" })).getByRole(
      "combobox",
    );
    expect(input).toHaveFocus();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    fireEvent.keyDown(window, { key: "K", metaKey: true });
    expect(screen.getByRole("dialog")).toBeVisible();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens with slash unless the user is typing in a field", () => {
    render(
      <>
        <input aria-label="Other field" />
        <CommandPalette search={vi.fn()} debounceMs={20} />
      </>,
    );
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Other field" }), { key: "/" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "/" });
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("shows suggestions and popular symbols with no query, as labelled groups", () => {
    pathname = "/backtest";
    render(<CommandPalette signedIn search={vi.fn()} debounceMs={20} />);
    const input = openPalette();
    const listbox = screen.getByRole("listbox", { name: "Results" });

    const suggested = within(listbox).getByRole("group", { name: "Suggested" });
    // The current workspace's other pages come first.
    expect(within(suggested).getAllByRole("option")[0]).toHaveTextContent("Saved runs");
    expect(within(listbox).getByRole("group", { name: "Popular Symbols" })).toBeVisible();
    // The first option is active, so Enter opens it.
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      within(suggested).getAllByRole("option")[0].id,
    );
    expect(within(suggested).getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("filters pages and actions as you type and opens one with Enter", async () => {
    render(<CommandPalette search={vi.fn().mockResolvedValue([])} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "screener" } });
    const group = screen.getByRole("group", { name: "Pages and Actions" });
    expect(within(group).getAllByRole("option")[0]).toHaveTextContent("Screener");
    fireEvent.keyDown(input, { key: "Enter" });

    expect(push).toHaveBeenCalledWith("/screener");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("moves with the arrow keys, wrapping at both ends", () => {
    render(<CommandPalette search={vi.fn().mockResolvedValue([])} debounceMs={20} />);
    const input = openPalette();
    fireEvent.change(input, { target: { value: "new backtest" } });
    const options = screen.getAllByRole("option");
    expect(options.length).toBeGreaterThan(0);

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input).toHaveAttribute("aria-activedescendant", options.at(-1)?.id);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
  });

  it("searches symbols and opens the stock page, keeping the chart state", async () => {
    pathname = "/stocks/MSFT";
    currentSearchParams = new URLSearchParams("tf=5Y&indicators=sma_50%2Crsi_14&unrelated=x");
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<CommandPalette search={search} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "aapl" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    const symbols = screen.getByRole("group", { name: "Symbols" });
    expect(
      within(symbols).getByRole("option", { name: /AAPL.*Apple Inc\..*NASDAQ/ }),
    ).toBeVisible();
    fireEvent.click(within(symbols).getByRole("option", { name: /AAPL/ }));
    expect(push).toHaveBeenCalledWith("/stocks/AAPL?tf=5Y&indicators=sma_50%2Crsi_14");
  });

  it("does not search for blank input and keeps the newest results", async () => {
    let resolveFirst!: (value: SymbolRow[]) => void;
    const first = new Promise<SymbolRow[]>((resolve) => {
      resolveFirst = resolve;
    });
    const search = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce([symbol("MSFT", "Microsoft")]);
    render(<CommandPalette search={search} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "   " } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(search).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    fireEvent.change(input, { target: { value: "mic" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(screen.getByText("Microsoft")).toBeVisible();
    await act(async () => resolveFirst([symbol("AAPL", "Apple Inc.")]));
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
  });

  it("says when symbol search is unavailable", async () => {
    render(<CommandPalette search={vi.fn().mockRejectedValue(new Error("x"))} debounceMs={20} />);
    const input = openPalette();
    fireEvent.change(input, { target: { value: "qqzz" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    expect(
      within(screen.getByRole("listbox")).getByText("Symbol search unavailable"),
    ).toBeVisible();
  });

  it("keeps the current book when opening a book page", () => {
    pathname = "/portfolio";
    currentSearchParams = new URLSearchParams("book=4");
    render(<CommandPalette signedIn search={vi.fn().mockResolvedValue([])} debounceMs={20} />);
    const input = openPalette();
    fireEvent.change(input, { target: { value: "orders" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/orders?book=4");
  });

  it("opens the book switcher for Switch book instead of navigating", () => {
    const listener = vi.fn();
    window.addEventListener(OPEN_BOOK_SWITCHER_EVENT, listener);
    render(<CommandPalette signedIn search={vi.fn().mockResolvedValue([])} debounceMs={20} />);
    const input = openPalette();
    fireEvent.change(input, { target: { value: "switch book" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(push).not.toHaveBeenCalled();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(OPEN_BOOK_SWITCHER_EVENT, listener);
  });

  it("remembers picks and lists them under Recent next time", () => {
    render(<CommandPalette search={vi.fn().mockResolvedValue([])} debounceMs={20} />);
    let input = openPalette();
    fireEvent.change(input, { target: { value: "event study" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/event-study");

    input = openPalette();
    const recent = screen.getByRole("group", { name: "Recent" });
    expect(within(recent).getByRole("option", { name: /Event study/ })).toBeVisible();
    expect(input).toHaveValue("");
  });
});
