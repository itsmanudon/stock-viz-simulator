// A7.6 (M7.7): a run saved from /backtest?experiment=<id> carries that experiment.
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/(product)/backtest/actions", () => ({
  saveBacktestRunAction: vi.fn(async () => ({})),
  rerunBacktestRunAction: vi.fn(async () => ({})),
}));

import { SaveStrategyRun } from "@/components/backtest-run-actions";
import type { StrategyRequest } from "@/lib/rule-strategy";

afterEach(() => window.history.pushState({}, "", "/"));

describe("experiment filing", () => {
  it("adds experiment_id from the URL", () => {
    window.history.pushState({}, "", "/backtest?experiment=7");
    const { container } = render(<SaveStrategyRun request={{} as StrategyRequest} />);
    expect(container.querySelector('input[name="experiment_id"]')).toHaveValue("7");
  });

  it("adds nothing without one", () => {
    const { container } = render(<SaveStrategyRun request={{} as StrategyRequest} />);
    expect(container.querySelector('input[name="experiment_id"]')).toBeNull();
  });
});
