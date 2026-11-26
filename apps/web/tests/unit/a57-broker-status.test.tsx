/**
 * A5.7: broker status in plain words. Each state on the status list, the
 * one-line form, an unreadable status, the imported book's empty state and
 * the switcher's note. Never an error, never a live-data claim.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/portfolio",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const { BrokerStatusLine, BrokerStatusList } = await import("@/components/brokers/broker-status");
const { PortfolioEmptyState } = await import("@/components/portfolio-empty-state");
const { BookSwitcher, IMPORTED_BOOK_NOTE } = await import("@/components/book-switcher");
const { IMPORT_LINE, brokerCopy, brokerLine } = await import("@/lib/broker-status");

type State = "not_configured" | "not_connected" | "offline" | "snapshot_only";

function zerodha(state: State, extra: Record<string, unknown> = {}) {
  return {
    label: "Zerodha",
    state,
    imported_books: 0,
    last_imported_at: null,
    last_snapshot_at: null,
    last_failure_at: null,
    ...extra,
  };
}

describe("brokerCopy", () => {
  it("says not set up when the Kite app is blank", () => {
    const c = brokerCopy(zerodha("not_configured"));
    expect(c.headline).toBe("Zerodha: not connected.");
    expect(c.detail).toBe("Live broker data needs a paid Kite Connect app; not set up.");
    expect(c.imports).toBe(IMPORT_LINE);
    expect(c.badge).toEqual({ label: "Not Set Up", tone: "neutral" });
  });

  it("words each configured state without claiming live data", () => {
    expect(brokerCopy(zerodha("not_connected")).detail).toMatch(/none has been taken yet/);
    const snap = brokerCopy(zerodha("snapshot_only", { last_snapshot_at: "2026-11-20T10:00:00" }));
    expect(snap.headline).toBe("Zerodha: snapshots only.");
    expect(snap.detail).toContain("Nov 20, 2026");
    expect(snap.detail).toContain("no live broker data");
    const off = brokerCopy(zerodha("offline", { last_failure_at: "2026-11-25T08:30:00" }));
    expect(off.headline).toBe("Zerodha: offline.");
    expect(off.detail).toContain("Nov 25, 2026");
    expect(off.badge.tone).toBe("warning");
  });

  it("counts imported books and says when none was uploaded", () => {
    expect(brokerCopy(zerodha("not_configured", { imported_books: 2 })).imports).toBe(
      `${IMPORT_LINE} 2 imported books; last upload: none yet.`,
    );
    expect(brokerCopy(zerodha("not_configured", { imported_books: 1 })).imports).toContain(
      "1 imported book;",
    );
  });

  it("gives the one-line form, and a line when the status is unreadable", () => {
    expect(brokerLine(zerodha("not_configured"))).toBe(
      "Zerodha: not connected. Imported books update when you upload a tradebook (CSV).",
    );
    expect(brokerLine(null)).toBe(`Zerodha: status unavailable. ${IMPORT_LINE}`);
  });
});

describe("BrokerStatusList", () => {
  it.each<[State, string, string]>([
    ["not_configured", "Zerodha: not connected.", "Not Set Up"],
    ["not_connected", "Zerodha: not connected.", "Not Connected"],
    ["snapshot_only", "Zerodha: snapshots only.", "Snapshots Only"],
    ["offline", "Zerodha: offline.", "Offline"],
  ])("renders %s", (state, headline, badge) => {
    render(<BrokerStatusList brokers={[zerodha(state)]} />);
    const list = screen.getByTestId("broker-status");
    const item = within(list).getByText(headline).closest("li");
    expect(item?.getAttribute("data-state")).toBe(state);
    expect(within(list).getByText(badge)).toBeTruthy();
    expect(within(list).getByText(IMPORT_LINE)).toBeTruthy();
    expect(list.textContent).not.toMatch(/error|failed to load/i);
  });

  it("says the status could not be read instead of failing", () => {
    render(<BrokerStatusList brokers={null} />);
    expect(screen.getByTestId("broker-status").textContent).toMatch(
      /could not be read just now.*tradebook \(CSV\)/,
    );
  });

  it("never puts capitals on its own labels", () => {
    const { container } = render(<BrokerStatusList brokers={[zerodha("offline")]} />);
    expect(container.innerHTML).not.toMatch(/\buppercase\b/);
  });
});

describe("imported book views", () => {
  it("shows the broker line in an imported book's empty state", () => {
    render(
      <PortfolioEmptyState
        availableCash="0"
        displayCurrency="INR"
        readOnly="Zerodha main is an imported book."
        broker={zerodha("not_configured")}
      />,
    );
    expect(screen.getByTestId("broker-status-line").textContent).toBe(
      "Zerodha: not connected. Imported books update when you upload a tradebook (CSV).",
    );
  });

  it("still shows a line when the status could not be read", () => {
    render(
      <PortfolioEmptyState availableCash="0" displayCurrency="INR" readOnly="x" broker="unknown" />,
    );
    expect(screen.getByTestId("broker-status-line").textContent).toContain("status unavailable");
  });

  it("leaves paper books alone", () => {
    render(<PortfolioEmptyState availableCash="100000" displayCurrency="USD" />);
    expect(screen.queryByTestId("broker-status-line")).toBeNull();
  });

  it("notes the broker under imported books in the switcher", () => {
    const base = {
      kind: "paper",
      is_default: true,
      base_currency: "INR",
      holder_kind: "self",
      holder_label: null,
      archived_at: null,
      writable: true,
    } as const;
    render(
      <BookSwitcher
        books={[
          { ...base, id: 1, name: "Default" },
          {
            ...base,
            id: 2,
            name: "Zerodha main",
            kind: "imported",
            is_default: false,
            writable: false,
          },
        ]}
        limit={20}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Switch book/ }));
    const notes = screen.getAllByTestId("switcher-broker-note");
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toBe(IMPORTED_BOOK_NOTE);
  });
});
