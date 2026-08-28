import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalTickerSearch } from "@/components/global-ticker-search";
import type { Symbol as SymbolRow } from "@/lib/api/types";

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

function openPalette() {
  fireEvent.click(screen.getByRole("combobox", { name: "Search tickers and companies" }));
  return within(screen.getByRole("dialog")).getByRole("combobox");
}

describe("GlobalTickerSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
    pathname = "/markets";
    currentSearchParams = new URLSearchParams();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not call symbol search for blank input", async () => {
    const search = vi.fn().mockResolvedValue([]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);

    fireEvent.change(openPalette(), { target: { value: "   " } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(search).not.toHaveBeenCalled();
  });

  it("shows complete symbol results and supports keyboard selection", async () => {
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(screen.getByRole("option", { name: /AAPL.*Apple Inc\..*NASDAQ/i })).toBeVisible();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(push).toHaveBeenCalledWith("/stocks/AAPL");
  });

  it("preserves chart analysis state when changing tickers from a stock workspace", async () => {
    pathname = "/stocks/MSFT";
    currentSearchParams = new URLSearchParams(
      "tf=5Y&indicators=sma_50%2Crsi_14&unrelated=discard-me",
    );
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    fireEvent.mouseDown(screen.getByRole("option", { name: /AAPL/i }));

    expect(push).toHaveBeenCalledWith("/stocks/AAPL?tf=5Y&indicators=sma_50%2Crsi_14");
  });

  it("preserves an explicitly empty indicator selection", async () => {
    pathname = "/stocks/MSFT";
    currentSearchParams = new URLSearchParams("tf=1Y&indicators=");
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);

    fireEvent.change(openPalette(), { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    fireEvent.mouseDown(screen.getByRole("option", { name: /AAPL/i }));

    expect(push).toHaveBeenCalledWith("/stocks/AAPL?tf=1Y&indicators=");
  });

  it("keeps the newest results when requests resolve out of order", async () => {
    let resolveFirst!: (value: SymbolRow[]) => void;
    const first = new Promise<SymbolRow[]>((resolve) => {
      resolveFirst = resolve;
    });
    const search = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce([symbol("MSFT", "Microsoft")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = openPalette();

    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));
    fireEvent.change(input, { target: { value: "mic" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(screen.getByText("Microsoft")).toBeVisible();
    await act(async () => resolveFirst([symbol("AAPL", "Apple Inc.")]));
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
  });

  it("reports an unavailable search and focuses with the advertised shortcut", async () => {
    const search = vi.fn().mockRejectedValue(new Error("offline"));
    render(<GlobalTickerSearch search={search} debounceMs={20} />);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = within(screen.getByRole("dialog")).getByRole("combobox");
    expect(input).toHaveFocus();

    fireEvent.change(input, { target: { value: "aapl" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(within(screen.getByRole("listbox")).getByText("Search unavailable")).toBeVisible();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("restores focus to the inline trigger after Escape", () => {
    render(<GlobalTickerSearch search={vi.fn()} debounceMs={20} />);
    const trigger = screen.getByRole("combobox", { name: "Search tickers and companies" });
    const input = openPalette();

    expect(input).toHaveFocus();
    fireEvent.keyDown(input, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("opens the centered palette with slash and exposes keyboard-selectable popular symbols", async () => {
    const search = vi.fn().mockResolvedValue([]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);

    fireEvent.keyDown(window, { key: "/" });

    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByRole("dialog")).toHaveClass(
      "fixed",
      "left-1/2",
      "top-1/2",
      "-translate-x-1/2",
      "-translate-y-1/2",
    );
    expect(screen.getByRole("dialog").parentElement).toBe(document.body);
    const overlay = document.body.querySelector('[data-state="open"].fixed.inset-0');
    expect(overlay).toBeTruthy();
    expect(overlay).toHaveClass("fixed", "inset-0", "z-50");
    expect(screen.getByText("Popular symbols")).toBeVisible();
    const input = within(screen.getByRole("dialog")).getByRole("combobox");
    await act(async () => {
      fireEvent.keyDown(input, { key: "ArrowDown" });
    });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(push).toHaveBeenCalledWith("/stocks/AAPL");
  });
});
