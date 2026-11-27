/** A9.11 (M11.4, M11.5): the research grid and the case for and against. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DebatePanel, GridPanel } from "@/components/copilot/research-panels";
import type { CheckedAnswer } from "@/lib/api/ai";

const doc = {
  id: 7,
  ticker: "TCS.NS",
  kind: "concall_transcript",
  source: "file",
  form_type: null,
  title: "TCS Q2",
  event_date: null,
  available_at: "2026-10-09T00:00:00",
  available_assumed: false,
  url: null,
  content_type: "text",
  text_chars: 50,
};

const answer = (text: string, grounded = true, warnings: string[] = []): CheckedAnswer => ({
  answer: text,
  grounded,
  cited: grounded ? [1] : [],
  invalid_citations: [],
  uncited_sentences: 0,
  warnings,
  sources: [
    {
      n: 1,
      cited: grounded,
      passage: {
        document: doc,
        chunk_id: 1,
        position: 0,
        start_char: 0,
        end_char: 20,
        text: "Sales grew nine percent.",
        score: 0.03,
        keyword_rank: 1,
        vector_rank: null,
        similarity: null,
      },
    },
  ],
});

const choices = [{ value: "server" as const, label: "Server: ollama gemma4:e4b" }];

describe("grid and debate", () => {
  it("builds the grid from the symbols and questions", async () => {
    const run = vi.fn().mockResolvedValue({
      grid: {
        as_of: "2027-01-01T00:00:00",
        tickers: ["TCS.NS", "INFY.NS"],
        questions: ["sales growth"],
        cells: [
          { ticker: "TCS.NS", question: "sales growth", result: answer("Sales grew [1].") },
          {
            ticker: "INFY.NS",
            question: "sales growth",
            result: answer("The stored documents do not cover this.", false),
          },
        ],
        model_calls: 1,
        provider: "ollama",
        model: "gemma4:e4b",
        disclaimer: "Not investment advice.",
      },
    });
    render(<GridPanel choices={choices} run={run} />);
    fireEvent.change(screen.getByLabelText("Symbols (Up to 5)"), {
      target: { value: "tcs.ns, infy.ns" },
    });
    fireEvent.change(screen.getByLabelText("Question 1"), { target: { value: "sales growth" } });
    fireEvent.click(screen.getByRole("button", { name: "Build Grid" }));
    await waitFor(() => expect(screen.getByTestId("grid-result")).toBeVisible());
    expect(run).toHaveBeenCalledWith("TCS.NS, INFY.NS", ["sales growth", "", ""], "server");
    const cells = screen.getAllByTestId("grid-cell");
    expect(cells[0]).toHaveAttribute("data-grounded", "true");
    expect(cells[1]).toHaveAttribute("data-grounded", "false");
    expect(screen.getByText(/1 model call\./)).toBeInTheDocument();
  });

  it("shows both sides with their warnings", async () => {
    const run = vi.fn().mockResolvedValue({
      debate: {
        ticker: "TCS.NS",
        topic: "growth",
        as_of: "2027-01-01T00:00:00",
        retrieval_mode: "keyword",
        case_for: answer("Sales grew [1]."),
        case_against: answer("Margins fell [1]. Demand may stay uneven.", true, [
          "1 sentence(s) carry no citation: check them against the sources.",
        ]),
        provider: "ollama",
        model: "gemma4:e4b",
        disclaimer: "Neither side is a recommendation.",
      },
    });
    render(<DebatePanel choices={choices} run={run} />);
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "tcs.ns" } });
    fireEvent.change(screen.getByLabelText("Topic"), { target: { value: "growth outlook" } });
    fireEvent.click(screen.getByRole("button", { name: "Argue Both Sides" }));
    await waitFor(() => expect(screen.getByTestId("debate-result")).toBeVisible());
    expect(run).toHaveBeenCalledWith("TCS.NS", "growth outlook", "server");
    expect(within(screen.getByTestId("case-against")).getByText(/carry no citation/)).toBeVisible();
    expect(screen.getByText(/from the same passages/)).toBeInTheDocument();
  });
});
