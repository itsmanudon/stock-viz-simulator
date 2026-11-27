// A8.2: a model draft is shown with its check; only a passing draft can be used.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RuleDraft } from "@/components/rule-draft";

describe("RuleDraft", () => {
  it("shows a passing draft and puts it in the editor on request", async () => {
    const onRule = vi.fn();
    const draft = vi.fn(async () => ({
      rule: "close > sma(close, 200) and rsi(14) < 40",
      valid: true,
      note: "Drafted by a model and checked by the rule checker.",
      model: "ollama gemma4:e4b",
    }));
    render(<RuleDraft model="ollama gemma4:e4b" draft={draft} onRule={onRule} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "above the 200 day, RSI under 40" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Draft Rule" }));
    await waitFor(() => expect(screen.getByTestId("rule-draft-result")).toBeTruthy());
    expect(screen.getByTestId("rule-draft-check").textContent).toBe("Passes the rule check.");
    fireEvent.click(screen.getByRole("button", { name: "Use This Rule" }));
    expect(onRule).toHaveBeenCalledWith("close > sma(close, 200) and rsi(14) < 40");
    expect(draft).toHaveBeenCalledWith("above the 200 day, RSI under 40");
  });

  it("shows a failing draft with its error and no way to use it", async () => {
    const draft = vi.fn(async () => ({
      rule: "roe > 18",
      valid: false,
      error: "write fundamental.roe",
    }));
    render(<RuleDraft model="ollama m" draft={draft} onRule={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ROE above 18" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft Rule" }));
    await waitFor(() =>
      expect(screen.getByTestId("rule-draft-check").textContent).toContain("write fundamental.roe"),
    );
    expect(screen.queryByRole("button", { name: "Use This Rule" })).toBeNull();
  });

  it("disables drafting until there are words", () => {
    render(<RuleDraft model="ollama m" draft={vi.fn()} onRule={vi.fn()} />);
    expect((screen.getByRole("button", { name: "Draft Rule" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});
