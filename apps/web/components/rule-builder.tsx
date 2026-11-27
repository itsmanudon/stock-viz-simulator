"use client";

/**
 * The visual rule builder (A8.1, M4.2): groups of conditions, `and` inside a
 * group and `or` between groups, written into the rule text as you build
 * (`lib/rule-builder.ts`). Drag a condition by its handle to reorder it or
 * move it to another group. The text stays the rule: it is checked by the
 * API like typed text and can be edited by hand afterwards.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  COMPARATOR_LABEL,
  type Comparator,
  type Condition,
  OPERANDS,
  type Operand,
  type OperandId,
  type RuleGroups,
  allowedComparators,
  conditionProblem,
  moveCondition,
  newCondition,
  toDsl,
} from "@/lib/rule-builder";

const SELECT = "h-8 rounded-sm border border-input bg-transparent px-2 text-xs";
const GROUPS = [...new Set(OPERANDS.map((o) => o.group))];
const SPEC = new Map(OPERANDS.map((o) => [o.id, o]));

function OperandPicker({
  value,
  onChange,
  label,
}: {
  value: Operand;
  onChange: (op: Operand) => void;
  label: string;
}) {
  const spec = SPEC.get(value.id);
  return (
    <span className="flex items-center gap-1">
      <select
        aria-label={label}
        className={SELECT}
        value={value.id}
        onChange={(e) => {
          const id = e.target.value as OperandId;
          onChange({ id, period: SPEC.get(id)?.period });
        }}
      >
        {GROUPS.map((g) => (
          <optgroup key={g} label={g}>
            {OPERANDS.filter((o) => o.group === g).map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {spec?.period !== undefined ? (
        <input
          aria-label={`${label} period`}
          className={`${SELECT} w-16`}
          inputMode="numeric"
          value={value.period ?? spec.period}
          onChange={(e) => onChange({ ...value, period: Number(e.target.value) || 0 })}
        />
      ) : null}
    </span>
  );
}

function ConditionRow({
  condition,
  onChange,
  onRemove,
  onDragStart,
}: {
  condition: Condition;
  onChange: (c: Condition) => void;
  onRemove: () => void;
  onDragStart: () => void;
}) {
  const right = condition.right;
  const comparators = allowedComparators(
    condition.left.id,
    right.kind === "operand" ? right.operand.id : null,
  );
  const problem = conditionProblem(condition);
  return (
    <li className="space-y-1" data-testid="builder-condition">
      <div className="flex flex-wrap items-center gap-1">
        <span
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData("text/plain", condition.key);
            onDragStart();
          }}
          className="cursor-grab select-none px-1 text-text-tertiary"
          title="Drag to reorder or move to another group"
          aria-hidden
        >
          ⠿
        </span>
        <OperandPicker
          label="Left side"
          value={condition.left}
          onChange={(left) => onChange({ ...condition, left })}
        />
        <select
          aria-label="Comparison"
          className={SELECT}
          value={condition.comparator}
          onChange={(e) => onChange({ ...condition, comparator: e.target.value as Comparator })}
        >
          {comparators.map((c) => (
            <option key={c} value={c}>
              {COMPARATOR_LABEL[c]}
            </option>
          ))}
        </select>
        <select
          aria-label="Compare with"
          className={SELECT}
          value={right.kind}
          onChange={(e) =>
            onChange({
              ...condition,
              right:
                e.target.value === "number"
                  ? { kind: "number", value: "0" }
                  : { kind: "operand", operand: { id: "sma", period: 50 } },
            })
          }
        >
          <option value="number">a number</option>
          <option value="operand">another value</option>
        </select>
        {right.kind === "number" ? (
          <input
            aria-label="Number"
            className={`${SELECT} w-24`}
            inputMode="decimal"
            value={right.value}
            onChange={(e) =>
              onChange({ ...condition, right: { kind: "number", value: e.target.value } })
            }
          />
        ) : (
          <OperandPicker
            label="Right side"
            value={right.operand}
            onChange={(operand) => onChange({ ...condition, right: { kind: "operand", operand } })}
          />
        )}
        <button
          type="button"
          className="text-xs text-text-tertiary hover:text-negative"
          onClick={onRemove}
          aria-label="Remove condition"
        >
          ✕
        </button>
      </div>
      {problem ? <p className="pl-5 text-2xs text-warning">{problem}</p> : null}
    </li>
  );
}

export function RuleBuilder({ onRule }: { onRule: (text: string) => void }) {
  const [groups, setGroups] = useState<RuleGroups>([[newCondition()]]);
  const [dragging, setDragging] = useState<string | null>(null);

  function update(next: RuleGroups) {
    setGroups(next);
    onRule(toDsl(next));
  }

  return (
    <div className="space-y-2 rounded-md border border-border-muted p-3" data-testid="rule-builder">
      {groups.map((group, gi) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: groups have no identity beyond their order
          key={gi}
          className="space-y-1"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const key = e.dataTransfer.getData("text/plain") || dragging;
            if (key) update(moveCondition(groups, key, gi, group.length));
            setDragging(null);
          }}
        >
          {gi > 0 ? (
            <p className="text-2xs font-semibold uppercase text-text-tertiary">or</p>
          ) : null}
          <ul className="space-y-1 rounded border border-dashed border-border-muted p-2">
            {group.map((cond, ci) => (
              <ConditionRow
                key={cond.key}
                condition={cond}
                onDragStart={() => setDragging(cond.key)}
                onChange={(c) =>
                  update(groups.map((g, k) => (k === gi ? g.map((x, j) => (j === ci ? c : x)) : g)))
                }
                onRemove={() =>
                  update(
                    groups
                      .map((g, k) => (k === gi ? g.filter((_x, j) => j !== ci) : g))
                      .filter((g, k) => g.length > 0 || k === 0),
                  )
                }
              />
            ))}
          </ul>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => update(groups.map((g, k) => (k === gi ? [...g, newCondition()] : g)))}
          >
            + And
          </Button>
        </div>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => update([...groups, [newCondition()]])}
      >
        + Or group
      </Button>
    </div>
  );
}
