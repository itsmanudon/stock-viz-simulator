"use client";

/**
 * The "Drawings" list (A3.2): every drawing on the symbol with edit, lock
 * and delete, and a form that adds one by typing dates and prices. This is
 * the keyboard path and the phone path: drawing by touch on a small chart is
 * hard, so any kind can be added and edited here. An anchored VWAP (A3.3)
 * takes a date only, a label (rules name it) and its bands.
 */

import { useId, useState } from "react";

import {
  DEFAULT_STYLE,
  DRAWING_COLOURS,
  type Drawing,
  type DrawingColour,
  type DrawingKind,
  type DrawingPoint,
  KIND_SPECS,
  describeDrawing,
  kindSpec,
  toPoints,
} from "@/lib/drawings/kinds";
import { positionStats } from "@/lib/drawings/math";
import { cn } from "@/lib/utils";

const FIELD =
  "h-8 w-full min-w-0 rounded-sm border border-border-muted bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60";
const BUTTON =
  "inline-flex h-7 items-center rounded-sm border border-border-muted px-2 text-2xs text-text-secondary transition-colors hover:bg-surface-hover hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

export type PointsDraft = {
  kind: DrawingKind;
  points: DrawingPoint[];
  label: string;
  colour: DrawingColour;
  /** Anchored VWAP bands, 0-2 (A3.3); other kinds ignore it. */
  bands?: number;
};

type Bounds = { first: string | null; last: string | null };

function emptyPoints(kind: DrawingKind, last: string | null): DrawingPoint[] {
  const spec = kindSpec(kind);
  return spec.steps.map((_, i) => ({
    ts:
      kind === "hline" || (spec.priceOnlyFrom !== undefined && i >= spec.priceOnlyFrom)
        ? null
        : (last ?? ""),
    price: "",
  }));
}

/** Check a typed drawing before it is sent; the API checks again. */
export function draftProblem(draft: PointsDraft, bounds: Bounds): string | null {
  const spec = kindSpec(draft.kind);
  for (const [i, p] of draft.points.entries()) {
    const price = Number(p.price);
    if (spec.dateOnly) {
      if (!p.ts) return `Enter a date for ${spec.steps[i]}.`;
    } else if (!p.price.trim() || !Number.isFinite(price) || price <= 0) {
      return `Enter a price above 0 for ${spec.steps[i]}.`;
    }
    if (p.ts !== null) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(p.ts)) return `Enter a date for ${spec.steps[i]}.`;
      if ((bounds.first && p.ts < bounds.first) || (bounds.last && p.ts > bounds.last)) {
        return `Dates must be between ${bounds.first} and ${bounds.last}, the stored bars.`;
      }
    }
  }
  if (draft.kind === "text" && !draft.label.trim()) return "A text note needs its text.";
  if (spec.needsLabel && !draft.label.trim()) {
    return 'Give it a label: rules name it, e.g. avwap("swing").';
  }
  if (draft.kind === "position_long" || draft.kind === "position_short") {
    const [entry, stop, target] = draft.points.map((p) => Number(p.price));
    const side = draft.kind === "position_long" ? "long" : "short";
    if (!positionStats(side, entry, stop, target).valid) {
      return side === "long"
        ? "A long position needs stop < entry < target."
        : "A short position needs target < entry < stop.";
    }
  }
  return null;
}

function PointsForm({
  initial,
  kindLocked,
  bounds,
  submitLabel,
  onSubmit,
  onCancel,
  busy,
}: {
  initial: PointsDraft;
  kindLocked: boolean;
  bounds: Bounds;
  submitLabel: string;
  onSubmit: (draft: PointsDraft) => void;
  onCancel?: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState<PointsDraft>(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const id = useId();
  const spec = kindSpec(draft.kind);

  const setPoint = (index: number, change: Partial<DrawingPoint>) =>
    setDraft((d) => ({
      ...d,
      points: d.points.map((p, i) => (i === index ? { ...p, ...change } : p)),
    }));

  return (
    <form
      className="grid gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const found = draftProblem(draft, bounds);
        setProblem(found);
        if (!found) onSubmit(draft);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && onCancel) {
          event.stopPropagation();
          onCancel();
        }
      }}
    >
      <div className="grid gap-2 sm:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]">
        {!kindLocked ? (
          <label className="grid gap-1 text-2xs text-text-tertiary">
            Kind
            <select
              className={FIELD}
              value={draft.kind}
              onChange={(event) => {
                const kind = event.target.value as DrawingKind;
                setDraft((d) => ({ ...d, kind, points: emptyPoints(kind, bounds.last) }));
              }}
              data-testid="drawing-add-kind"
            >
              {KIND_SPECS.map((s) => (
                <option key={s.kind} value={s.kind}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {draft.points.map((point, i) => (
          <fieldset key={`${draft.kind}-${spec.steps[i]}`} className="grid gap-1">
            <legend className="mb-1 text-2xs text-text-tertiary">
              {spec.steps[i][0].toUpperCase() + spec.steps[i].slice(1)}
            </legend>
            {point.ts !== null ? (
              <input
                type="date"
                aria-label={`${spec.steps[i]} date`}
                className={FIELD}
                value={point.ts}
                min={bounds.first ?? undefined}
                max={bounds.last ?? undefined}
                onChange={(event) => setPoint(i, { ts: event.target.value })}
              />
            ) : null}
            {spec.dateOnly ? null : (
              <input
                type="text"
                inputMode="decimal"
                aria-label={`${spec.steps[i]} price`}
                placeholder="Price"
                className={cn(FIELD, "font-mono")}
                value={point.price}
                onChange={(event) => setPoint(i, { price: event.target.value.trim() })}
                data-testid={`drawing-price-${i}`}
              />
            )}
          </fieldset>
        ))}
        <label className="grid gap-1 text-2xs text-text-tertiary">
          {draft.kind === "text" ? "Text" : spec.needsLabel ? "Label" : "Label (optional)"}
          <input
            type="text"
            maxLength={80}
            className={FIELD}
            value={draft.label}
            onChange={(event) => setDraft((d) => ({ ...d, label: event.target.value }))}
            data-testid="drawing-label"
          />
        </label>
        {draft.kind === "avwap" ? (
          <label className="grid gap-1 text-2xs text-text-tertiary">
            Bands
            <select
              className={FIELD}
              value={draft.bands ?? 0}
              onChange={(event) => setDraft((d) => ({ ...d, bands: Number(event.target.value) }))}
              data-testid="drawing-bands"
            >
              <option value={0}>None</option>
              <option value={1}>±1σ</option>
              <option value={2}>±1σ and ±2σ</option>
            </select>
          </label>
        ) : null}
        <label className="grid gap-1 text-2xs text-text-tertiary">
          Colour
          <select
            className={FIELD}
            value={draft.colour}
            onChange={(event) =>
              setDraft((d) => ({ ...d, colour: event.target.value as DrawingColour }))
            }
          >
            {DRAWING_COLOURS.map((c) => (
              <option key={c} value={c}>
                {c === "foreground" ? "White" : c[0].toUpperCase() + c.slice(1)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {problem ? (
        <p id={`${id}-problem`} role="alert" className="text-2xs text-negative">
          {problem}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button type="submit" className={BUTTON} disabled={busy} data-testid="drawing-submit">
          {submitLabel}
        </button>
        {onCancel ? (
          <button type="button" className={BUTTON} onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}

type ListProps = {
  drawings: Drawing[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onAdd: (draft: PointsDraft) => void;
  onEdit: (drawing: Drawing, draft: PointsDraft) => void;
  onToggleLock: (drawing: Drawing) => void;
  onDelete: (drawing: Drawing) => void;
  enabled: boolean;
  busy: boolean;
  bounds: Bounds;
  limit: number;
};

export function DrawingsList({
  drawings,
  selectedId,
  onSelect,
  onAdd,
  onEdit,
  onToggleLock,
  onDelete,
  enabled,
  busy,
  bounds,
  limit,
}: ListProps) {
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className="space-y-2 px-1" data-testid="drawings-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-xs font-medium text-foreground">
          Drawings{" "}
          <span className="font-mono text-text-tertiary">
            {drawings.length}
            {drawings.length >= limit ? ` (limit ${limit})` : ""}
          </span>
        </h3>
        <button
          type="button"
          className={BUTTON}
          disabled={!enabled || drawings.length >= limit}
          aria-expanded={adding}
          onClick={() => setAdding((v) => !v)}
          data-testid="drawing-add-toggle"
        >
          {adding ? "Close" : "Add by typing"}
        </button>
      </div>
      {adding && enabled ? (
        <div className="rounded-sm border border-border-muted p-2">
          <PointsForm
            initial={{
              kind: "hline",
              points: emptyPoints("hline", bounds.last),
              label: "",
              colour: DEFAULT_STYLE.colour,
            }}
            kindLocked={false}
            bounds={bounds}
            submitLabel="Add drawing"
            busy={busy}
            onSubmit={(draft) => {
              onAdd(draft);
              setAdding(false);
            }}
            onCancel={() => setAdding(false)}
          />
        </div>
      ) : null}
      {drawings.length === 0 ? (
        <p className="text-2xs text-text-tertiary">
          {enabled
            ? "No drawings yet. Pick a tool beside the chart and click to place it, or add one by typing."
            : "No drawings."}
        </p>
      ) : (
        <ul className="divide-y divide-border-muted rounded-sm border border-border-muted">
          {drawings.map((drawing) => {
            const selected = drawing.id === selectedId;
            return (
              <li
                key={drawing.id}
                className={cn("p-2", selected && "bg-surface-hover")}
                data-testid="drawing-item"
                data-kind={drawing.kind}
                data-drawing-id={drawing.id}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(selected ? null : drawing.id)}
                    className="min-w-0 flex-1 text-left text-2xs leading-5 text-text-secondary hover:text-foreground"
                  >
                    {drawing.locked ? <span className="sr-only">Locked. </span> : null}
                    {describeDrawing(drawing)}
                    {drawing.position ? (
                      <span className="font-mono text-text-tertiary">
                        {" "}
                        · R:R 1:{drawing.position.reward_risk} · risk{" "}
                        {Number(drawing.position.risk_per_share)}/share
                      </span>
                    ) : null}
                  </button>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      className={BUTTON}
                      disabled={!enabled || drawing.locked || busy}
                      onClick={() => setEditing(editing === drawing.id ? null : drawing.id)}
                      aria-expanded={editing === drawing.id}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className={BUTTON}
                      disabled={!enabled || busy}
                      onClick={() => onToggleLock(drawing)}
                      aria-pressed={drawing.locked}
                    >
                      {drawing.locked ? "Unlock" : "Lock"}
                    </button>
                    <button
                      type="button"
                      className={BUTTON}
                      disabled={!enabled || drawing.locked || busy}
                      onClick={() => onDelete(drawing)}
                      aria-label={`Delete ${describeDrawing(drawing)}`}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                {editing === drawing.id && !drawing.locked ? (
                  <div className="mt-2">
                    <PointsForm
                      initial={{
                        kind: drawing.kind,
                        points: toPoints(drawing.points),
                        label: drawing.label ?? "",
                        colour: drawing.style.colour,
                        bands: drawing.style.bands ?? 0,
                      }}
                      kindLocked
                      bounds={bounds}
                      submitLabel="Save"
                      busy={busy}
                      onSubmit={(draft) => {
                        onEdit(drawing, draft);
                        setEditing(null);
                      }}
                      onCancel={() => setEditing(null)}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
