import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as actions from "@/app/(product)/(authed)/watchlist/actions";
import { AddToListMenu, BulkAddToWatchlist } from "@/components/add-to-list";
import { ColumnSetEditor, ColumnSetPicker } from "@/components/watchlist-columns";
import { ListManager, ListTabs } from "@/components/watchlist-lists";
import { NoteEditor, TagEditor } from "@/components/watchlist-row-editors";
import type { components } from "@/lib/api/schema";
import type { WatchlistList } from "@/lib/api/watchlist";
import {
  COLUMN_KEYS,
  DEFAULT_COLUMNS,
  formatColumnValue,
  hasTag,
  moveListId,
  parseTagInput,
  tagsOf,
} from "@/lib/watchlist-columns";

const refresh = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh, replace: vi.fn() }),
}));

vi.mock("@/app/(product)/(authed)/watchlist/actions", () => ({
  toggleWatchlistAction: vi.fn(async () => ({})),
  createListAction: vi.fn(async () => ({})),
  updateListAction: vi.fn(async () => ({})),
  makeDefaultListAction: vi.fn(async () => ({ ok: true })),
  moveListAction: vi.fn(async () => ({ ok: true })),
  deleteListAction: vi.fn(async () => ({ ok: true })),
  saveItemAction: vi.fn(async () => ({ ok: true })),
  saveTagsAction: vi.fn(async () => ({ ok: true })),
  setListMembershipAction: vi.fn(async () => ({ ok: true })),
  bulkAddAction: vi.fn(async () => ({ ok: true, message: "Added 2.", listId: 7 })),
  saveColumnSetAction: vi.fn(async () => ({ ok: true, message: "Saved" })),
  chooseColumnSetAction: vi.fn(async () => ({ ok: true })),
  deleteColumnSetAction: vi.fn(async () => ({ ok: true })),
}));

function list(overrides: Partial<WatchlistList>): WatchlistList {
  return {
    id: 1,
    name: "Default",
    colour: "aqua",
    position: 0,
    is_default: true,
    column_set_id: null,
    item_count: 0,
    contains: null,
    created_at: "2026-11-26T00:00:00",
    ...overrides,
  };
}

const LISTS = [
  list({ id: 1, name: "Default", item_count: 3 }),
  list({ id: 2, name: "Earnings watch", colour: "amber", position: 1, is_default: false }),
  list({ id: 3, name: "Stage 2", colour: "violet", position: 2, is_default: false }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("watchlist column helpers", () => {
  it("covers exactly the API's column allow-list", () => {
    type ApiKey = components["schemas"]["ColumnSetOut"]["columns"][number];
    const all: Record<ApiKey, true> = Object.fromEntries(
      COLUMN_KEYS.map((k) => [k, true]),
    ) as Record<ApiKey, true>;
    expect(Object.keys(all)).toHaveLength(19);
    expect(DEFAULT_COLUMNS).toEqual([
      "close",
      "change_pct",
      "rsi_14",
      "pct_from_52w_high",
      "sector",
    ]);
  });

  it("formats each kind and dashes missing data, never 0", () => {
    const values = {
      close: 2800,
      change_pct: -1.234,
      volume_ratio: 2,
      market_cap_usd: 3e12,
      checklist_met: 4,
      checklist_evaluated: 5,
      sector: "Technology",
      rsi_14: null,
    };
    expect(formatColumnValue("close", values, "JPY")).toBe("¥2,800");
    expect(formatColumnValue("change_pct", values)).toBe("-1.23%");
    expect(formatColumnValue("volume_ratio", values)).toBe("2.00×");
    expect(formatColumnValue("market_cap_usd", values)).toBe("$3T");
    expect(formatColumnValue("checklist_met", values)).toBe("4 of 5");
    expect(formatColumnValue("sector", values)).toBe("Technology");
    expect(formatColumnValue("rsi_14", values)).toBe("—");
    expect(formatColumnValue("pe", {})).toBe("—");
  });

  it("collects tags, filters by tag ignoring case, moves list ids", () => {
    const rows = [{ tags: ["Stage 2", "earnings"] }, { tags: ["stage 2"] }, { tags: [] }];
    expect(tagsOf(rows)).toEqual(["earnings", "Stage 2"]);
    expect(rows.filter((r) => hasTag(r, "STAGE 2"))).toHaveLength(2);
    expect(moveListId([1, 2, 3], 2, -1)).toEqual([2, 1, 3]);
    expect(moveListId([1, 2, 3], 3, 1)).toEqual([1, 2, 3]);
    expect(parseTagInput(" earnings,  f&o   liquid ,,")).toEqual(["earnings", "f&o liquid"]);
  });
});

describe("list switcher (A2.5)", () => {
  it("links every list, marks the open one and the default", () => {
    render(<ListTabs lists={LISTS} activeId={2} />);
    const nav = screen.getByRole("navigation", { name: "Watchlists" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/watchlist?list=1",
      "/watchlist?list=2",
      "/watchlist?list=3",
    ]);
    expect(links[1]).toHaveAttribute("aria-current", "page");
    expect(within(links[0]).getByLabelText("Default list")).toBeInTheDocument();
  });

  it("moves the open list with buttons and disables the ends", async () => {
    render(<ListManager lists={LISTS} active={LISTS[0]} />);
    expect(screen.getByRole("button", { name: "Move Default left" })).toBeDisabled();
    const right = screen.getByRole("button", { name: "Move Default right" });
    await act(async () => fireEvent.click(right));
    expect(actions.moveListAction).toHaveBeenCalledWith(1, 1);
    expect(refresh).toHaveBeenCalled();
    // The default list says so instead of offering "Make default".
    expect(screen.queryByRole("button", { name: "Make default" })).toBeNull();
  });

  it("makes another list the default", async () => {
    render(<ListManager lists={LISTS} active={LISTS[2]} />);
    expect(screen.getByRole("button", { name: "Move Stage 2 right" })).toBeDisabled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Make default" })));
    expect(actions.makeDefaultListAction).toHaveBeenCalledWith(3);
  });

  it("asks once more before deleting, naming the symbols that go", async () => {
    render(<ListManager lists={LISTS} active={LISTS[0]} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Default" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Default");
    fireEvent.click(screen.getByRole("button", { name: "Delete Default…" }));
    const confirm = screen.getByRole("group", { name: "Confirm delete" });
    expect(confirm).toHaveTextContent("Delete Default and its 3 symbols?");
    expect(confirm).toHaveTextContent("The next list becomes your default.");
    expect(actions.deleteListAction).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group", { name: "Confirm delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Delete Default…" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Delete list" })));
    expect(actions.deleteListAction).toHaveBeenCalledWith(1);
    expect(push).toHaveBeenCalledWith("/watchlist");
  });

  it("says an empty Default replaces the only list", () => {
    render(<ListManager lists={[LISTS[0]]} active={LISTS[0]} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Default" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Default…" }));
    expect(screen.getByRole("group", { name: "Confirm delete" })).toHaveTextContent(
      "an empty Default list takes its place",
    );
  });
});

describe("column set picker and editor (A2.5)", () => {
  const sets = [
    {
      id: 5,
      name: "Momentum",
      columns: ["close", "rsi_14"] as const,
      created_at: "2026-11-26T00:00:00",
      updated_at: "2026-11-26T00:00:00",
    },
  ].map((s) => ({ ...s, columns: [...s.columns] }));

  it("saves the chosen set on the list, or the default columns", async () => {
    render(<ColumnSetPicker listId={2} sets={sets} activeSetId={null} />);
    const select = screen.getByLabelText("Columns");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Default columns", "Momentum"]);
    await act(async () => fireEvent.change(select, { target: { value: "5" } }));
    expect(actions.chooseColumnSetAction).toHaveBeenCalledWith(2, 5);
    await act(async () => fireEvent.change(select, { target: { value: "" } }));
    expect(actions.chooseColumnSetAction).toHaveBeenLastCalledWith(2, null);
  });

  it("adds, removes and orders columns with keyboard-reachable buttons", () => {
    const { container } = render(
      <ColumnSetEditor listId={2} set={sets[0]} columns={["close", "rsi_14"]} />,
    );
    const hidden = () =>
      Array.from(container.querySelectorAll<HTMLInputElement>('input[name="columns"]')).map(
        (i) => i.value,
      );
    expect(hidden()).toEqual(["close", "rsi_14"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show P/E" }));
    expect(hidden()).toEqual(["close", "rsi_14", "pe"]);
    fireEvent.click(screen.getByRole("button", { name: "Move P/E up" }));
    expect(hidden()).toEqual(["close", "pe", "rsi_14"]);
    expect(screen.getByRole("button", { name: "Move Last close up" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Show Last close" }));
    expect(hidden()).toEqual(["pe", "rsi_14"]);
    expect(screen.getByRole("button", { name: "Save Momentum" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save as new set" })).toBeEnabled();
  });

  it("cannot save an empty set", () => {
    render(<ColumnSetEditor listId={2} set={null} columns={["close"]} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show Last close" }));
    expect(screen.getByRole("button", { name: "Save column set" })).toBeDisabled();
    expect(screen.getByText("Pick at least one column.")).toBeInTheDocument();
  });
});

describe("note and tag editing (A2.5)", () => {
  it("edits a note in place, saves it, and Escape cancels", async () => {
    render(<NoteEditor listId={2} ticker="AAPL" note={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Add a note for AAPL" }));
    const box = screen.getByLabelText("Note for AAPL");
    fireEvent.change(box, { target: { value: "Base above the 200-day" } });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByLabelText("Note for AAPL")).toBeNull();
    expect(actions.saveItemAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Add a note for AAPL" }));
    fireEvent.change(screen.getByLabelText("Note for AAPL"), {
      target: { value: "  Base above the 200-day " },
    });
    expect(screen.getByText("25/2000")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save note" })));
    expect(actions.saveItemAction).toHaveBeenCalledWith(2, "AAPL", {
      note: "Base above the 200-day",
    });
    expect(screen.getByTestId("watchlist-note")).toHaveTextContent("Base above the 200-day");
    expect(screen.getByRole("button", { name: "Edit note for AAPL" })).toBeInTheDocument();
  });

  it("keeps the editor open with the error when the save fails", async () => {
    vi.mocked(actions.saveItemAction).mockResolvedValueOnce({
      error: "A note is at most 2000 characters",
    });
    render(<NoteEditor listId={2} ticker="AAPL" note="Old" />);
    fireEvent.click(screen.getByRole("button", { name: "Edit note for AAPL" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save note" })));
    expect(screen.getByRole("alert")).toHaveTextContent("at most 2000");
    expect(screen.getByLabelText("Note for AAPL")).toBeInTheDocument();
  });

  it("adds tags without duplicates and removes one", async () => {
    render(<TagEditor listId={2} ticker="AAPL" tags={["Stage 2"]} />);
    const input = screen.getByLabelText("Add tags to AAPL");
    fireEvent.change(input, { target: { value: "stage 2, earnings" } });
    await act(async () => fireEvent.submit(input.closest("form") as HTMLFormElement));
    expect(actions.saveItemAction).toHaveBeenCalledWith(2, "AAPL", {
      tags: ["Stage 2", "earnings"],
    });
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Remove tag Stage 2 from AAPL" })),
    );
    expect(actions.saveItemAction).toHaveBeenLastCalledWith(2, "AAPL", { tags: ["earnings"] });
    expect(
      within(screen.getByRole("list", { name: "Tags on AAPL" })).queryByText("Stage 2"),
    ).toBeNull();
  });
});

describe("bulk add and Add to list (A2.5)", () => {
  const choices = LISTS.map((l) => ({ id: l.id, name: l.name, colour: l.colour }));

  it("adds the ticked screener rows to the chosen list", async () => {
    render(
      <form>
        <input type="checkbox" name="tickers" value="AAPL" defaultChecked />
        <input type="checkbox" name="tickers" value="MSFT" />
        <input type="checkbox" name="tickers" value="NVDA" defaultChecked />
        <BulkAddToWatchlist lists={choices} mode="selected" />
      </form>,
    );
    fireEvent.change(screen.getByLabelText("Watchlist to add to"), { target: { value: "3" } });
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Add selected to list" })),
    );
    const data = vi.mocked(actions.bulkAddAction).mock.calls[0][1] as FormData;
    expect(data.getAll("tickers")).toEqual(["AAPL", "NVDA"]);
    expect(data.get("watchlist_id")).toBe("3");
    expect(await screen.findByText(/Added 2\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open list" })).toHaveAttribute(
      "href",
      "/watchlist?list=7",
    );
  });

  it("adds every result to a new list on a phone", async () => {
    render(<BulkAddToWatchlist lists={choices} mode="all" tickers={["AAPL", "MSFT"]} />);
    fireEvent.change(screen.getByLabelText("Watchlist to add to"), { target: { value: "new" } });
    fireEvent.change(screen.getByLabelText("New list name"), { target: { value: "Breakouts" } });
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "Add these 2 to a list" })),
    );
    const data = vi.mocked(actions.bulkAddAction).mock.calls[0][1] as FormData;
    expect(data.getAll("tickers")).toEqual(["AAPL", "MSFT"]);
    expect(data.get("new_list")).toBe("Breakouts");
    expect(data.get("watchlist_id")).toBeNull();
  });

  it("ticks and unticks lists from the stock page", async () => {
    render(
      <AddToListMenu ticker="AAPL" lists={choices.map((c) => ({ ...c, contains: c.id === 1 }))} />,
    );
    const toggle = screen.getByRole("button", { name: "Add AAPL to a list" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([true, false, false]);
    await act(async () => fireEvent.click(boxes[1]));
    expect(actions.setListMembershipAction).toHaveBeenCalledWith(2, "AAPL", true);
    await act(async () => fireEvent.click(boxes[0]));
    expect(actions.setListMembershipAction).toHaveBeenLastCalledWith(1, "AAPL", false);
    // A failed change puts the box back.
    vi.mocked(actions.setListMembershipAction).mockResolvedValueOnce({ error: "Nope" });
    await act(async () => fireEvent.click(boxes[2]));
    await waitFor(() => expect((boxes[2] as HTMLInputElement).checked).toBe(false));
    expect(screen.getByRole("alert")).toHaveTextContent("Nope");
    fireEvent.keyDown(boxes[2], { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
