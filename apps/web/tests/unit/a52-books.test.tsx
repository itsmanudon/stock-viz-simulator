/**
 * A5.2: the book switcher, the URL rule, tickets in books that take no
 * trades, the settings forms and the All books change over a range.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/portfolio";
let search = new URLSearchParams();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useSearchParams: () => search,
  useRouter: () => ({ replace, push: vi.fn() }),
}));

vi.mock("@/app/(product)/(authed)/trade/actions", () => ({
  placeTradeAction: vi.fn().mockResolvedValue({}),
  placeOrderAction: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/app/(product)/(authed)/settings/book-actions", () => ({
  createBookAction: vi.fn().mockResolvedValue({}),
  renameBookAction: vi.fn().mockResolvedValue({}),
  bookStateAction: vi.fn().mockResolvedValue({}),
  deleteBookAction: vi.fn().mockResolvedValue({}),
}));

const { BookSwitcher, switchHref } = await import("@/components/book-switcher");
const { BooksPanel } = await import("@/components/books-panel");
const { OrderTicket } = await import("@/components/order-ticket");
const { BookLink } = await import("@/components/book-link");
const { bookIdFromForm, holderText, parseBookParam, tradeBlockReason, withBookHref } = await import(
  "@/lib/book-url"
);
const { calculateNavChange } = await import("@/lib/portfolio-view-model");

type Summary = Parameters<typeof tradeBlockReason>[0] & object;

const usd = {
  id: 1,
  name: "Default",
  kind: "paper",
  is_default: true,
  base_currency: "USD",
  holder_kind: "self",
  holder_label: null,
  archived_at: null,
  writable: true,
  activity: ["trades"],
} as const;
const inr = {
  ...usd,
  id: 2,
  name: "India growth",
  is_default: false,
  base_currency: "INR",
  holder_kind: "family",
  holder_label: "Asha",
  activity: [],
} as const;
const archived = {
  ...usd,
  id: 3,
  name: "Old book",
  is_default: false,
  archived_at: "2026-11-20T00:00:00Z",
  writable: false,
} as const;
const imported = {
  ...usd,
  id: 4,
  name: "Zerodha",
  kind: "imported",
  is_default: false,
  base_currency: "INR",
  writable: false,
  activity: [],
} as const;
const books = [usd, inr, archived, imported];

beforeEach(() => {
  pathname = "/portfolio";
  search = new URLSearchParams();
  replace.mockReset();
});

describe("book URL rule", () => {
  it("parses ids and all, and nothing else", () => {
    expect(parseBookParam("12")).toBe(12);
    expect(parseBookParam("all")).toBe("all");
    for (const bad of ["0", "-1", "1.5", "x", "", "ALL", undefined]) {
      expect(parseBookParam(bad)).toBeNull();
    }
  });

  it("sets the book on book pages, keeps other parameters, drops all where it has no view", () => {
    expect(withBookHref("/portfolio?tab=analytics&range=1y", 2)).toBe(
      "/portfolio?tab=analytics&range=1y&book=2",
    );
    expect(withBookHref("/trade?ticker=AAPL", "all")).toBe("/trade?ticker=AAPL&book=all");
    expect(withBookHref("/settings#books", "all")).toBe("/settings#books");
    expect(withBookHref("/markets", 2)).toBe("/markets");
    expect(withBookHref("/orders?book=3", null)).toBe("/orders");
  });

  it("names why a ticket can't trade", () => {
    expect(tradeBlockReason("all")).toMatch(/read-only/);
    expect(tradeBlockReason(archived as Summary)).toMatch(/archived/);
    expect(tradeBlockReason(imported as Summary)).toMatch(/imported book/);
    expect(tradeBlockReason(inr as Summary)).toBeNull();
    expect(holderText(inr)).toBe("Family · Asha");
  });

  it("reads the posted book id", () => {
    const form = new FormData();
    expect(bookIdFromForm(form)).toBeNull();
    form.set("book_id", "all");
    expect(bookIdFromForm(form)).toBeNull();
    form.set("book_id", "4");
    expect(bookIdFromForm(form)).toBe(4);
  });

  it("switches in place on a book page and drops journal state, else opens the dashboard", () => {
    expect(switchHref("/portfolio", "tab=journal&month=2026-11&date=2026-11-03", 2)).toBe(
      "/portfolio?tab=journal&month=2026-11&book=2",
    );
    expect(switchHref("/settings", "", "all")).toBe("/portfolio?book=all");
    expect(switchHref("/markets", "", 2)).toBe("/dashboard?book=2");
  });

  it("carries the page's book on links between book pages", () => {
    search = new URLSearchParams("book=2");
    render(
      <>
        <BookLink href="/trade?ticker=AAPL">Trade</BookLink>
        <BookLink href="/stocks/AAPL">Research</BookLink>
      </>,
    );
    expect(screen.getByRole("link", { name: "Trade" })).toHaveAttribute(
      "href",
      "/trade?ticker=AAPL&book=2",
    );
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/stocks/AAPL");
  });
});

describe("BookSwitcher", () => {
  it("shows the URL's book and lists every book with its badges, then All books and Manage", () => {
    search = new URLSearchParams("book=2&tab=analytics");
    render(<BookSwitcher books={[...books]} limit={20} />);
    const button = screen.getByRole("button", { name: /Book: India growth \(INR\)/ });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    const list = screen.getByRole("list", { name: "Books" });
    const links = within(list).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      expect.stringContaining("All books"),
      expect.stringContaining("Default"),
      expect.stringContaining("India growth"),
      expect.stringContaining("Old book"),
      expect.stringContaining("Zerodha"),
    ]);
    expect(links[2]).toHaveAttribute("aria-current", "true");
    expect(links[2]).toHaveAttribute("href", "/portfolio?book=2&tab=analytics");
    expect(links[0]).toHaveAttribute("href", "/portfolio?book=all&tab=analytics");
    expect(links[2]).toHaveTextContent("Family · Asha");
    expect(links[3]).toHaveTextContent("Archived");
    expect(links[4]).toHaveTextContent("Imported");
    expect(screen.getByText(/4 of 20/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage books" })).toHaveAttribute(
      "href",
      "/settings#books",
    );
  });

  it("is keyboard friendly: arrows move through the links, Escape closes and refocuses", () => {
    render(<BookSwitcher books={[...books]} limit={20} />);
    const button = screen.getByRole("button", { name: /Book: Default/ });
    fireEvent.click(button);
    const links = within(screen.getByRole("list", { name: "Books" })).getAllByRole("link");
    links[0].focus();
    fireEvent.keyDown(links[0], { key: "ArrowDown" });
    expect(links[1]).toHaveFocus();
    fireEvent.keyDown(links[1], { key: "ArrowUp" });
    expect(links[0]).toHaveFocus();
    fireEvent.keyDown(links[0], { key: "Escape" });
    expect(screen.queryByRole("list", { name: "Books" })).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("offers no All books with a single book and remembers a choice in a cookie", () => {
    render(<BookSwitcher books={[usd]} limit={20} />);
    fireEvent.click(screen.getByRole("button", { name: /Book: Default/ }));
    expect(screen.queryByText("All books")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /Default/ }));
    expect(document.cookie).toContain("sv_book=1");
  });

  it("reads All books from the URL", () => {
    search = new URLSearchParams("book=all");
    render(<BookSwitcher books={[...books]} limit={20} />);
    expect(screen.getByRole("button", { name: "Book: All books. Switch book" })).toBeVisible();
  });
});

describe("tickets", () => {
  const props = {
    symbols: [{ ticker: "AAPL", name: "Apple", currency: "USD" }],
    initialTicker: "AAPL",
    quoteClose: "100",
    quoteAt: "2026-11-25T00:00:00Z",
    position: null,
    availableCash: "1000",
    displayCurrency: "USD",
  };

  it("says which book it trades into and posts its id", () => {
    const { container } = render(
      <OrderTicket {...props} book={{ id: 2, name: "India growth", currency: "INR" }} />,
    );
    expect(screen.getByTestId("ticket-book")).toHaveTextContent("Trades into India growth (INR)");
    expect(container.querySelector('input[name="book_id"]')).toHaveValue("2");
    expect(screen.getByRole("button", { name: /Review/ })).not.toBeDisabled();
  });

  it("is disabled with the reason in an archived book and in All books", () => {
    const { rerender } = render(
      <OrderTicket
        {...props}
        book={{ id: 3, name: "Old book", currency: "USD" }}
        blockedReason={tradeBlockReason(archived as Summary)}
      />,
    );
    expect(screen.getByTestId("ticket-blocked")).toHaveTextContent(/Old book is archived/);
    expect(screen.getByRole("button", { name: /Review/ })).toBeDisabled();

    rerender(<OrderTicket {...props} book={null} blockedReason={tradeBlockReason("all")} />);
    expect(screen.getByTestId("ticket-blocked")).toHaveTextContent(/read-only/);
    expect(screen.getByRole("button", { name: /Review/ })).toBeDisabled();
  });

  it("keeps the book when the symbol changes", () => {
    search = new URLSearchParams("book=2");
    render(
      <OrderTicket
        {...props}
        symbols={[...props.symbols, { ticker: "MSFT", name: "Microsoft", currency: "USD" }]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "MSFT" } });
    expect(replace).toHaveBeenCalledWith("/portfolio?book=2&ticker=MSFT", { scroll: false });
  });
});

describe("Settings → Books", () => {
  it("lists the books with the cap and their controls; the default has no archive or delete", () => {
    render(<BooksPanel books={[...books]} limit={20} />);
    expect(screen.getByText("4 of 20 books")).toBeInTheDocument();
    const def = within(screen.getByTestId("book-row-1"));
    expect(def.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(def.queryByRole("button", { name: "Delete…" })).not.toBeInTheDocument();
    expect(def.getByText(/can't be archived or deleted/)).toBeInTheDocument();

    const india = within(screen.getByTestId("book-row-2"));
    expect(india.getByRole("button", { name: "Make default" })).toBeInTheDocument();
    expect(india.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(india.getByText(/INR/)).toBeInTheDocument();

    const old = within(screen.getByTestId("book-row-3"));
    expect(old.getByRole("button", { name: "Unarchive" })).toBeInTheDocument();
    expect(old.queryByRole("button", { name: "Make default" })).not.toBeInTheDocument();
    // An imported book can't be the default either.
    expect(
      within(screen.getByTestId("book-row-4")).queryByRole("button", { name: "Make default" }),
    ).not.toBeInTheDocument();
  });

  it("deletes in two steps: names what goes, then needs the name typed back", () => {
    render(<BooksPanel books={[...books]} limit={20} />);
    const old = within(screen.getByTestId("book-row-3"));
    fireEvent.click(old.getByRole("button", { name: "Delete…" }));
    const form = within(screen.getByRole("form", { name: "Delete Old book" }));
    expect(form.getByText(/removes everything in it for good: its trades/)).toBeInTheDocument();
    const confirm = form.getByRole("button", { name: "Delete book" });
    expect(confirm).toBeDisabled();
    fireEvent.change(form.getByLabelText(/Type the book/), { target: { value: "Old" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(form.getByLabelText(/Type the book/), { target: { value: "Old book" } });
    expect(confirm).not.toBeDisabled();
  });

  it("refuses to delete a book with activity until it is archived", () => {
    const active = { ...inr, activity: ["trades", "orders"] };
    render(<BooksPanel books={[usd, active]} limit={20} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete…" }));
    expect(screen.getByText(/must be archived before it can be deleted/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete book" })).toBeDisabled();
  });

  it("creates with name, currency, kind and holder, and has no PAN field", () => {
    render(<BooksPanel books={[usd]} limit={20} />);
    const create = within(screen.getByRole("form", { name: "New book" }));
    expect(create.getByLabelText("Name")).toBeRequired();
    expect(create.getByLabelText("Currency")).toHaveDisplayValue(/USD/);
    expect(create.getByLabelText("Kind")).toBeInTheDocument();
    expect(create.getByLabelText("Whose money")).toBeInTheDocument();
    expect(create.getByLabelText(/Holder label/)).toBeInTheDocument();
    expect(create.queryByLabelText(/PAN/)).not.toBeInTheDocument();
    expect(create.getByText(/Don't enter a PAN/)).toBeInTheDocument();
  });

  it("turns the create form off at the cap", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ ...inr, id: i + 10, name: `B${i}` }));
    render(<BooksPanel books={many} limit={20} />);
    expect(screen.getByText(/limit is reached/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create book" })).toBeDisabled();
  });
});

describe("All books change over a range", () => {
  it("leaves out a new book's opening value and chains the returns", () => {
    // The API test's example: 100,000 then 221,000 with 120,000 in, then 228,250.
    const change = calculateNavChange([
      { date: "2026-11-02", nav: "100000", flow: "0" },
      { date: "2026-11-03", nav: "221000", flow: "120000" },
      { date: "2026-11-04", nav: "228250", flow: "0" },
    ]);
    expect(change?.absolute).toBeCloseTo(8250, 6);
    expect(change?.percent).toBeCloseTo(4.313348, 5);
  });

  it("is last minus first without flows", () => {
    const change = calculateNavChange([
      { date: "2026-11-02", nav: "100" },
      { date: "2026-11-03", nav: "110" },
    ]);
    expect(change?.absolute).toBe(10);
    expect(change?.percent).toBeCloseTo(10, 9);
  });
});
