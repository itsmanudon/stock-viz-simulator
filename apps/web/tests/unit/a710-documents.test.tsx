// A7.10: document rows say when each became public and mark the searched phrase.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DocumentRow, filingHref, markParts } from "@/components/documents-view";
import type { DocumentItem } from "@/lib/api/documents";

const doc: DocumentItem = {
  id: 7,
  ticker: "TCS.NS",
  kind: "concall_transcript",
  source: "file",
  title: "Q2 FY27 earnings call",
  available_at: "2026-10-09T18:29:00",
  available_assumed: true,
  content_type: "html",
  text_chars: 5000,
};

describe("documents view", () => {
  it("splits text around case-insensitive matches", () => {
    expect(markParts("Order book grew; ORDER book", "order book")).toEqual([
      { text: "Order book", hit: true },
      { text: " grew; ", hit: false },
      { text: "ORDER book", hit: true },
    ]);
    expect(markParts("abc", "")).toEqual([{ text: "abc", hit: false }]);
  });

  it("links with the query and states the release time", () => {
    expect(filingHref(7, "order book")).toBe("/filings/7?q=order%20book");
    render(
      <DocumentRow doc={doc} q="order book" matches={2} snippets={["…the Order book grew…"]} />,
    );
    expect(screen.getByRole("link", { name: "Q2 FY27 earnings call" }).getAttribute("href")).toBe(
      "/filings/7?q=order%20book",
    );
    const meta = screen.getByTestId("document-meta").textContent ?? "";
    expect(meta).toContain("Concall Transcript");
    expect(meta).toContain("Assumed: End of Its Date");
    expect(meta).toContain("Placed by Hand");
    expect(screen.getByTestId("document-matches").textContent).toBe("2 Matches");
    expect(screen.getByText("Order book").tagName).toBe("MARK");
  });
});
