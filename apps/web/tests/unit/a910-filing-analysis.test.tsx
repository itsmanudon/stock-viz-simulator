/** A9.10 (M11.3): what changed between filings, and verified figures. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentChanges, FigureExtractor, hedgingLine } from "@/components/filing-analysis";
import type { DocumentCompare } from "@/lib/api/documents";

const doc = {
  id: 2,
  ticker: "ACME",
  kind: "annual_report",
  source: "file",
  form_type: "10-K",
  title: "10-K 2026",
  event_date: null,
  available_at: "2026-02-01T00:00:00",
  available_assumed: false,
  url: null,
  content_type: "html",
  text_chars: 900,
};

const data: DocumentCompare = {
  document: doc,
  against: { ...doc, id: 1, title: "10-K 2025" },
  scope: "risk_factors",
  scope_note: null,
  paragraphs_before: 3,
  paragraphs_after: 3,
  unchanged: 1,
  added: 1,
  removed: 1,
  changed: 1,
  changes: [
    {
      kind: "added",
      before: null,
      after: "New export controls may restrict sales.",
      similarity: null,
    },
    {
      kind: "changed",
      before: "Customers in North America.",
      after: "Customers in North America and Europe.",
      similarity: 0.83,
    },
  ],
  truncated: false,
  hedging_before: { words: 100, hedges: 2, per_thousand: 20, top: [] },
  hedging_after: { words: 100, hedges: 3, per_thousand: 30, top: [] },
  note: "10-K 2026 compared with the earlier 10-K 2025.",
  method: "Paragraphs matched in order. Not of evasiveness or intent.",
};

describe("filing analysis", () => {
  it("summarises the changes and the hedging rate", () => {
    expect(hedgingLine(data)).toBe("Hedging words: 20 → 30 per 1,000 words (+10).");
    expect(hedgingLine({ ...data, against: null, hedging_before: null })).toBe(
      "Hedging words: 30 per 1,000 words.",
    );
    render(<DocumentChanges data={data} />);
    expect(screen.getByTestId("document-change-counts")).toHaveTextContent(
      "Risk factors: 1 added · 1 removed · 1 reworded · 1 unchanged",
    );
    const items = screen.getAllByTestId("document-change");
    expect(items[1]).toHaveTextContent("Reworded · 83% Similar");
  });

  it("shows only verified figures and counts the dropped ones", async () => {
    const extract = vi.fn().mockResolvedValue({
      result: {
        document: doc,
        figures: [
          {
            metric: "Revenue",
            value: "64,259",
            unit: "crore",
            period: "Q2",
            quote: "Revenue was 64,259 crore",
            chunk_id: 1,
            position: 0,
          },
        ],
        passages_read: 3,
        dropped: { "quote not in the text": 2 },
        provider: "ollama",
        model: "gemma4:e4b",
        method: "Kept only when its quote appears word for word.",
        disclaimer: "Not investment advice.",
      },
    });
    render(
      <FigureExtractor
        documentId={2}
        choices={[{ value: "server", label: "Server" }]}
        extract={extract}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Extract Figures" }));
    await waitFor(() =>
      expect(screen.getByTestId("figure")).toHaveTextContent("Revenue 64,259 crore · Q2"),
    );
    expect(extract).toHaveBeenCalledWith(2, "server");
    expect(screen.getByTestId("figures-dropped")).toHaveTextContent(
      "Dropped: 2 (quote not in the text).",
    );
  });
});
