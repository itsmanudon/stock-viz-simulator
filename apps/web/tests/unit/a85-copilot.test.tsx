/** A8.5 (M11.2): the copilot's answer, citations and sources. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CopilotAnswerView, CopilotPanel } from "@/components/copilot/copilot-panel";
import type { CopilotAnswer } from "@/lib/api/ai";
import { answerParts, questionProblem } from "@/lib/copilot";

const doc = {
  id: 7,
  ticker: "TCS.NS",
  kind: "concall_transcript",
  source: "file",
  form_type: null,
  title: "TCS Q2 concall",
  event_date: null,
  available_at: "2026-10-09T18:29:00",
  available_assumed: false,
  url: null,
  content_type: "pdf",
  text_chars: 120,
};

const answer: CopilotAnswer = {
  question: "how did borrowings change",
  as_of: "2027-02-01T00:00:00",
  retrieval_mode: "hybrid",
  answer: "Borrowings were repaid in full [1]. Margins rose [3].",
  grounded: true,
  cited: [1],
  invalid_citations: [3],
  uncited_sentences: 0,
  sources: [
    {
      n: 1,
      cited: true,
      passage: {
        document: doc,
        chunk_id: 1,
        position: 0,
        start_char: 0,
        end_char: 30,
        text: "Borrowings were repaid in full.",
        score: 0.03,
        keyword_rank: 1,
        vector_rank: 1,
        similarity: 0.7,
      },
    },
    {
      n: 2,
      cited: false,
      passage: {
        document: { ...doc, id: 8, title: "TCS Q3 concall" },
        chunk_id: 2,
        position: 0,
        start_char: 0,
        end_char: 20,
        text: "Headcount fell.",
        score: 0.01,
        keyword_rank: null,
        vector_rank: 2,
        similarity: 0.3,
      },
    },
  ],
  provider: "ollama",
  model: "gemma4:e4b",
  warnings: ["The model cited sources that do not exist: [3]."],
  notes: [],
  disclaimer: "Written by a model from the passages listed. Not investment advice.",
};

describe("copilot", () => {
  it("splits an answer into text and checked citations", () => {
    expect(answerParts("A [1]. B [2, 4].", 2)).toEqual([
      { kind: "text", text: "A " },
      { kind: "cite", n: 1, valid: true },
      { kind: "text", text: ". B " },
      { kind: "cite", n: 2, valid: true },
      { kind: "cite", n: 4, valid: false },
      { kind: "text", text: "." },
    ]);
    expect(answerParts("No citations.", 3)).toEqual([{ kind: "text", text: "No citations." }]);
    expect(questionProblem("hey")).toMatch(/five characters/);
    expect(questionProblem("What about margins?")).toBeNull();
  });

  it("links valid citations to their source and marks the rest", () => {
    render(<CopilotAnswerView answer={answer} />);
    const cite = screen.getByTestId("copilot-cite");
    expect(cite).toHaveAttribute("href", "#source-1");
    expect(screen.getByTestId("copilot-cite-invalid")).toHaveTextContent("[3?]");
    expect(screen.getByTestId("copilot-warnings")).toHaveTextContent("do not exist: [3]");
    const sources = screen.getAllByTestId("copilot-source");
    expect(sources).toHaveLength(2);
    expect(sources[0]).toHaveAttribute("data-cited", "true");
    expect(sources[1]).toHaveTextContent("Not Cited");
    expect(screen.getByRole("link", { name: "TCS Q2 concall" })).toHaveAttribute(
      "href",
      "/filings/7",
    );
    expect(screen.getByTestId("copilot-disclaimer")).toHaveTextContent("Not investment advice");
  });

  it("asks with the question and symbol, and shows errors", async () => {
    const ask = vi
      .fn()
      .mockResolvedValueOnce({ error: "NOPE is not stored." })
      .mockResolvedValueOnce({ answer });
    render(
      <CopilotPanel
        choices={[
          { value: "server", label: "Server: ollama gemma4:e4b" },
          { value: "openai_compatible", label: "Your key: gpt-test" },
        ]}
        ask={ask}
      />,
    );
    const button = screen.getByRole("button", { name: "Ask" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: "How did borrowings change?" },
    });
    fireEvent.change(screen.getByLabelText("Symbol (Optional)"), { target: { value: "nope" } });
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("NOPE is not stored."));
    expect(ask).toHaveBeenCalledWith("How did borrowings change?", "NOPE", "server");
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "openai_compatible" } });
    expect(screen.getByText(/Billed to your account/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByTestId("copilot-answer")).toBeVisible());
    expect(ask).toHaveBeenLastCalledWith("How did borrowings change?", "NOPE", "openai_compatible");
  });
});
