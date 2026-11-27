/** A8.4 (M11.1): ranked passages on /filings. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PassageRow, passageRanks } from "@/components/documents-view";
import type { Passage } from "@/lib/api/documents";

const passage: Passage = {
  document: {
    id: 7,
    ticker: "TCS.NS",
    kind: "concall_transcript",
    source: "file",
    form_type: null,
    title: "TCS Q2 concall",
    event_date: null,
    available_at: "2026-10-09T18:29:00",
    available_assumed: true,
    url: null,
    content_type: "pdf",
    text_chars: 120,
  },
  chunk_id: 3,
  position: 1,
  start_char: 0,
  end_char: 40,
  text: "Sales grew nine percent in the quarter.",
  score: 0.03,
  keyword_rank: null,
  vector_rank: 1,
  similarity: 0.8123,
};

describe("passages", () => {
  it("says how each passage was ranked", () => {
    expect(passageRanks(passage)).toBe("Meaning #1 (0.81)");
    expect(passageRanks({ keyword_rank: 2, vector_rank: 4, similarity: 0.5 })).toBe(
      "Words #2 · Meaning #4 (0.50)",
    );
    expect(passageRanks({ keyword_rank: 1, vector_rank: null, similarity: null })).toBe("Words #1");
  });

  it("renders the passage with its document and a link", () => {
    render(<PassageRow passage={passage} />);
    expect(screen.getByRole("link", { name: "TCS Q2 concall" })).toHaveAttribute(
      "href",
      "/filings/7",
    );
    expect(screen.getByText(/Sales grew nine percent/)).toBeInTheDocument();
    expect(screen.getByTestId("passage-ranks")).toHaveTextContent("Passage 2 · Meaning #1 (0.81)");
  });
});
