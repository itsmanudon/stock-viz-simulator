// A8.1: the builder writes the rule text as you build.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RuleBuilder } from "@/components/rule-builder";

describe("RuleBuilder", () => {
  it("writes conditions and groups into the rule", () => {
    const onRule = vi.fn();
    render(<RuleBuilder onRule={onRule} />);
    const row = screen.getAllByTestId("builder-condition")[0];
    fireEvent.change(within(row).getByLabelText("Left side"), { target: { value: "rsi" } });
    fireEvent.change(within(row).getByLabelText("Compare with"), { target: { value: "number" } });
    fireEvent.change(within(row).getByLabelText("Number"), { target: { value: "30" } });
    fireEvent.change(within(row).getByLabelText("Comparison"), { target: { value: "<" } });
    expect(onRule).toHaveBeenLastCalledWith("rsi(14) < 30");
    fireEvent.click(screen.getByRole("button", { name: "+ Or group" }));
    expect(onRule).toHaveBeenLastCalledWith("rsi(14) < 30 or close > sma(close, 50)");
    fireEvent.click(screen.getAllByRole("button", { name: "+ And" })[0]);
    expect(onRule).toHaveBeenLastCalledWith(
      "(rsi(14) < 30 and close > sma(close, 50)) or close > sma(close, 50)",
    );
  });

  it("offers no crossing on a fundamental", () => {
    render(<RuleBuilder onRule={() => {}} />);
    const row = screen.getAllByTestId("builder-condition")[0];
    fireEvent.change(within(row).getByLabelText("Left side"), { target: { value: "pe" } });
    const options = [...within(row).getByLabelText("Comparison").querySelectorAll("option")].map(
      (o) => o.textContent,
    );
    expect(options).not.toContain("crosses above");
    expect(options).toContain("is below");
  });
});
