import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalTickerSearch } from "@/components/global-ticker-search";
import type { Symbol as SymbolRow } from "@/lib/api/types";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
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

describe("GlobalTickerSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not call symbol search for blank input", async () => {
    const search = vi.fn().mockResolvedValue([]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "   " } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(search).not.toHaveBeenCalled();
  });

  it("shows complete symbol results and supports keyboard selection", async () => {
    const search = vi.fn().mockResolvedValue([symbol("AAPL", "Apple Inc.")]);
    render(<GlobalTickerSearch search={search} debounceMs={20} />);
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "app" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(screen.getByRole("option", { name: /AAPL.*Apple Inc\..*NASDAQ/i })).toBeVisible();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(push).toHaveBeenCalledWith("/stocks/AAPL");
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
    const input = screen.getByRole("combobox");

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
    const input = screen.getByRole("combobox");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(input).toHaveFocus();

    fireEvent.change(input, { target: { value: "aapl" } });
    await act(() => vi.advanceTimersByTimeAsync(20));

    expect(within(screen.getByRole("listbox")).getByText("Search unavailable")).toBeVisible();
  });
});
