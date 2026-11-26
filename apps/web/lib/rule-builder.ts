/**
 * The visual rule builder (A8.1, M4.2 visual half): groups of conditions
 * that compile to Rule DSL text. Conditions inside a group are joined by
 * `and`; groups by `or`. Pure and browser-safe; the text it makes is checked
 * by `/v1/rules/check` like any typed rule, and the user can always edit it.
 */

export type OperandId =
  | "close"
  | "open"
  | "high"
  | "low"
  | "volume"
  | "sma"
  | "ema"
  | "rsi"
  | "atr_pct"
  | "return"
  | "high_n"
  | "low_n"
  | "avg_volume"
  | "pe"
  | "pb"
  | "roe"
  | "market_cap"
  | "dividend_yield"
  | "delivery_pct";

export type OperandSpec = {
  id: OperandId;
  label: string;
  group: "Price" | "Studies" | "Fundamentals" | "Delivery";
  /** The default period for operands that take one. */
  period?: number;
  text: (period: number) => string;
};

/** Every operand compiles in the DSL (checked against the API in the batch's tests). */
export const OPERANDS: OperandSpec[] = [
  { id: "close", label: "Close", group: "Price", text: () => "close" },
  { id: "open", label: "Open", group: "Price", text: () => "open" },
  { id: "high", label: "High", group: "Price", text: () => "high" },
  { id: "low", label: "Low", group: "Price", text: () => "low" },
  { id: "volume", label: "Volume", group: "Price", text: () => "volume" },
  {
    id: "sma",
    label: "SMA of close",
    group: "Studies",
    period: 50,
    text: (n) => `sma(close, ${n})`,
  },
  {
    id: "ema",
    label: "EMA of close",
    group: "Studies",
    period: 20,
    text: (n) => `ema(close, ${n})`,
  },
  { id: "rsi", label: "RSI", group: "Studies", period: 14, text: (n) => `rsi(${n})` },
  {
    id: "atr_pct",
    label: "ATR % of close",
    group: "Studies",
    period: 14,
    text: (n) => `atr(${n}) / close * 100`,
  },
  {
    id: "return",
    label: "Return % over N",
    group: "Studies",
    period: 126,
    text: (n) => `pct_change(close, ${n})`,
  },
  {
    id: "high_n",
    label: "Highest high over N",
    group: "Studies",
    period: 252,
    text: (n) => `highest(high, ${n})`,
  },
  {
    id: "low_n",
    label: "Lowest low over N",
    group: "Studies",
    period: 20,
    text: (n) => `lowest(low, ${n})`,
  },
  {
    id: "avg_volume",
    label: "Average volume over N",
    group: "Studies",
    period: 20,
    text: (n) => `sma(volume, ${n})`,
  },
  { id: "pe", label: "P/E", group: "Fundamentals", text: () => "fundamental.pe" },
  { id: "pb", label: "P/B", group: "Fundamentals", text: () => "fundamental.pb" },
  { id: "roe", label: "ROE %", group: "Fundamentals", text: () => "fundamental.roe" },
  {
    id: "market_cap",
    label: "Market cap",
    group: "Fundamentals",
    text: () => "fundamental.market_cap",
  },
  {
    id: "dividend_yield",
    label: "Dividend yield %",
    group: "Fundamentals",
    text: () => "fundamental.dividend_yield",
  },
  { id: "delivery_pct", label: "Delivery %", group: "Delivery", text: () => "delivery_pct" },
];

/** Fundamentals are point in time: no bar history, so no crossing (the DSL refuses one). */
export function isPointInTime(id: OperandId): boolean {
  return SPEC_GROUP.get(id) === "Fundamentals";
}

/** The comparators a condition may use, given its operands. */
export function allowedComparators(
  left: OperandId,
  right: OperandId | null,
): readonly Comparator[] {
  const pit = isPointInTime(left) || (right !== null && isPointInTime(right));
  return pit ? COMPARATORS.filter((c) => !c.startsWith("crosses")) : COMPARATORS;
}

export const COMPARATORS = [">", ">=", "<", "<=", "crosses_above", "crosses_below"] as const;
export type Comparator = (typeof COMPARATORS)[number];

export const COMPARATOR_LABEL: Record<Comparator, string> = {
  ">": "is above",
  ">=": "is at or above",
  "<": "is below",
  "<=": "is at or below",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
};

export type Operand = { id: OperandId; period?: number; multiplier?: number };

export type Condition = {
  key: string;
  left: Operand;
  comparator: Comparator;
  right: { kind: "number"; value: string } | { kind: "operand"; operand: Operand };
};

export type RuleGroups = Condition[][];

const SPEC = new Map(OPERANDS.map((o) => [o.id, o]));
const SPEC_GROUP = new Map(OPERANDS.map((o) => [o.id, o.group]));

let counter = 0;
export function newKey(): string {
  counter += 1;
  return `c${Date.now().toString(36)}${counter}`;
}

export function operandText(op: Operand): string {
  const spec = SPEC.get(op.id);
  if (!spec) throw new Error(`unknown operand ${op.id}`);
  const period = op.period ?? spec.period ?? 0;
  const text = spec.text(period);
  return op.multiplier && op.multiplier !== 1 ? `${op.multiplier} * ${text}` : text;
}

export function conditionText(c: Condition): string {
  const right = c.right.kind === "number" ? c.right.value.trim() : operandText(c.right.operand);
  return `${operandText(c.left)} ${c.comparator} ${right}`;
}

/** Why a condition cannot compile yet, or null. */
export function conditionProblem(c: Condition): string | null {
  const right = c.right.kind === "operand" ? c.right.operand.id : null;
  if (!allowedComparators(c.left.id, right).includes(c.comparator)) {
    return "Fundamentals have no bar history: use above or below, not a crossing.";
  }
  for (const op of [c.left, ...(c.right.kind === "operand" ? [c.right.operand] : [])]) {
    const spec = SPEC.get(op.id);
    if (
      spec?.period !== undefined &&
      !(Number.isInteger(op.period ?? spec.period) && (op.period ?? spec.period) > 0)
    ) {
      return `${spec.label}: the period is a whole number above 0.`;
    }
  }
  if (c.right.kind === "number" && !Number.isFinite(Number(c.right.value)))
    return "Enter a number.";
  if (c.right.kind === "number" && !c.right.value.trim()) return "Enter a number.";
  return null;
}

/** The groups as one Rule DSL condition: `(a and b) or (c)`; empty groups are skipped. */
export function toDsl(groups: RuleGroups): string {
  const parts = groups.filter((g) => g.length > 0).map((g) => g.map(conditionText).join(" and "));
  if (parts.length <= 1) return parts[0] ?? "";
  return parts
    .map((p, i) => (groups.filter((g) => g.length)[i].length > 1 ? `(${p})` : p))
    .join(" or ");
}

export function newCondition(): Condition {
  return {
    key: newKey(),
    left: { id: "close" },
    comparator: ">",
    right: { kind: "operand", operand: { id: "sma", period: 50 } },
  };
}

/** Move the condition ``key`` to group ``toGroup`` before index ``toIndex`` (drag and drop). */
export function moveCondition(
  groups: RuleGroups,
  key: string,
  toGroup: number,
  toIndex: number,
): RuleGroups {
  let moving: Condition | null = null;
  let fromGroup = -1;
  let fromIndex = -1;
  groups.forEach((g, gi) =>
    g.forEach((c, ci) => {
      if (c.key === key) {
        moving = c;
        fromGroup = gi;
        fromIndex = ci;
      }
    }),
  );
  if (!moving) return groups;
  const next = groups.map((g) => g.filter((c) => c.key !== key));
  let index = toIndex;
  if (fromGroup === toGroup && fromIndex < toIndex) index -= 1;
  const target = next[toGroup] ?? [];
  next[toGroup] = [...target.slice(0, index), moving, ...target.slice(index)];
  return next;
}
