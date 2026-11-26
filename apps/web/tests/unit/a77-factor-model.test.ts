// A7.7: a factor model builds the rotation request with factors instead of a ranking.
import { describe, expect, it } from "vitest";

import {
  FACTOR_PRESETS,
  buildRotationRequest,
  initialRotationForm,
  rotationProblem,
} from "@/lib/rotation";

const base = initialRotationForm(["AAPL", "MSFT", "NVDA"], {
  from: "2024-01-01",
  to: "2025-01-01",
});

describe("factor model request", () => {
  it("sends factors and no ranking in factor mode", () => {
    const req = buildRotationRequest({ ...base, mode: "factors", topN: "2" });
    expect(req.ranking).toBeNull();
    expect(req.factors).toEqual([
      {
        name: "Momentum 12-1",
        expression: FACTOR_PRESETS[0].expression,
        weight: 1,
        higher_is_better: true,
      },
      { name: "Low volatility", expression: "atr(14) / close", weight: 1, higher_is_better: false },
    ]);
  });

  it("keeps the single ranking otherwise", () => {
    const req = buildRotationRequest(base);
    expect(req.ranking).toBe(base.ranking);
    expect(req.factors).toBeNull();
  });

  it("says what is wrong with the factors", () => {
    expect(rotationProblem({ ...base, mode: "factors", factors: [] }, true)).toMatch(
      /at least one/,
    );
    const bad = {
      ...base,
      mode: "factors" as const,
      factors: [{ ...FACTOR_PRESETS[0], weight: "0" }],
    };
    expect(rotationProblem(bad, true)).toMatch(/weights/);
    expect(rotationProblem({ ...base, mode: "factors", topN: "2" }, false)).toBeNull();
  });
});
