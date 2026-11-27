// A8.1 (M4.2): the visual rule builder's model.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  COMPARATORS,
  type Condition,
  OPERANDS,
  conditionProblem,
  moveCondition,
  operandText,
  toDsl,
} from "@/lib/rule-builder";

const c = (
  key: string,
  left: Condition["left"],
  comparator: Condition["comparator"],
  right: Condition["right"],
): Condition => ({ key, left, comparator, right }); // prettier-ignore
const num = (value: string) => ({ kind: "number" as const, value });
const op = (operand: Condition["left"]) => ({ kind: "operand" as const, operand });

describe("toDsl", () => {
  it("joins a group with and, groups with or, parenthesised", () => {
    const a = c("a", { id: "close" }, ">", op({ id: "sma", period: 50 }));
    const b = c("b", { id: "rsi" }, ">=", num("50"));
    const d = c("d", { id: "pe" }, "<", num("10"));
    expect(toDsl([[a, b]])).toBe("close > sma(close, 50) and rsi(14) >= 50");
    expect(toDsl([[a, b], [d]])).toBe(
      "(close > sma(close, 50) and rsi(14) >= 50) or fundamental.pe < 10",
    );
    expect(toDsl([[], [d], []])).toBe("fundamental.pe < 10");
    expect(toDsl([])).toBe("");
  });

  it("writes multipliers and periods", () => {
    expect(operandText({ id: "avg_volume", period: 50, multiplier: 2 })).toBe(
      "2 * sma(volume, 50)",
    );
    expect(operandText({ id: "high_n" })).toBe("highest(high, 252)");
  });

  it("names what is missing", () => {
    expect(conditionProblem(c("x", { id: "close" }, ">", num("")))).toMatch(/number/);
    expect(conditionProblem(c("x", { id: "sma", period: 0 }, ">", num("1")))).toMatch(/period/);
    expect(conditionProblem(c("x", { id: "close" }, ">", num("10")))).toBeNull();
  });
});

describe("moveCondition", () => {
  const a = c("a", { id: "close" }, ">", num("1"));
  const b = c("b", { id: "close" }, ">", num("2"));
  const d = c("d", { id: "close" }, ">", num("3"));
  it("reorders within a group and moves across groups", () => {
    expect(moveCondition([[a, b, d]], "a", 0, 3)[0].map((x) => x.key)).toEqual(["b", "d", "a"]);
    const moved = moveCondition([[a, b], [d]], "b", 1, 0);
    expect(moved.map((g) => g.map((x) => x.key))).toEqual([["a"], ["b", "d"]]);
  });
});

describe("the operand catalogue", () => {
  it("matches the fixture the API compiles (tests/test_a81_rule_builder.py)", () => {
    const fixture = JSON.parse(
      readFileSync(
        join(__dirname, "../../../api/tests/fixtures/rule_builder_operands.json"),
        "utf8",
      ),
    ) as { operands: string[]; comparators: string[] };
    expect(OPERANDS.map((o) => operandText({ id: o.id }))).toEqual(fixture.operands);
    expect([...COMPARATORS]).toEqual(fixture.comparators);
  });
});
