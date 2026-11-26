"use client";

/**
 * The price pane's context menu (A6.7, M2.11) and the plan editor it opens.
 *
 * Opened by a right-click, a long press on a phone, or the Menu key /
 * Shift+F10 on the focused chart (`chart-tools.tsx` wires those and builds
 * the items from `lib/chart-menu.ts`). A menu in the WAI-ARIA sense: the
 * first item takes focus, arrow keys move, Home/End jump, Escape (or a click
 * outside) closes and gives focus back to the chart. Signed out, the items
 * are replaced by a sign-in link. The note under the items says how alerts
 * are judged (on the next stored bar unless a stream is running).
 */

import Link from "next/link";
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { PlanPrefill } from "@/lib/chart-menu";
import { planFigures } from "@/lib/plans";

export type ChartMenuItem = {
  id: "price" | "drawing" | "indicator" | "plan";
  label: string;
  /** What the item does, in words (the price, the drawing, the study). */
  detail: string;
  /** Why the item can't be used here, or null. */
  disabled: string | null;
  onSelect: () => void;
};

export function ChartContextMenu({
  at,
  items,
  note,
  signedIn,
  signInHref,
  onClose,
}: {
  /** Viewport position (the pointer, or the crosshair for the keyboard). */
  at: { left: number; top: number };
  items: ChartMenuItem[];
  note: string;
  signedIn: boolean;
  signInHref: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>('[role="menuitem"], a');
    first?.focus();
    const onDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", onDown, true);
    return () => window.removeEventListener("pointerdown", onDown, true);
  }, [onClose]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const entries = [...(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    const index = entries.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    if (event.key === "ArrowDown") next = (index + 1) % entries.length;
    else if (event.key === "ArrowUp") next = (index - 1 + entries.length) % entries.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = entries.length - 1;
    else if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (next !== null && entries.length) {
      event.preventDefault();
      entries[next]?.focus();
    }
  };

  // Keep the menu on screen: open leftwards / upwards near the right and bottom edges.
  const width = 288;
  const left =
    typeof window === "undefined"
      ? at.left
      : Math.max(8, Math.min(at.left, window.innerWidth - width - 8));
  const top =
    typeof window === "undefined"
      ? at.top
      : Math.max(8, Math.min(at.top, window.innerHeight - 320));

  return (
    <div
      ref={ref}
      role="menu"
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      onContextMenu={(event) => event.preventDefault()}
      className="fixed z-50 w-72 rounded-md border border-border bg-surface-elevated p-1 text-xs shadow-lg outline-none"
      style={{ left, top }}
      data-testid="chart-context-menu"
    >
      <p id={titleId} className="px-2 pt-1 pb-1.5 text-2xs font-medium text-text-tertiary">
        Chart Actions
      </p>
      {signedIn ? (
        items.map((item) => (
          <button
            key={item.id}
            type="button"
            role="menuitem"
            aria-disabled={item.disabled ? true : undefined}
            onClick={() => {
              if (item.disabled) return;
              item.onSelect();
              onClose();
            }}
            className={`flex w-full flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left outline-none transition-colors focus-visible:bg-surface-hover ${
              item.disabled ? "cursor-not-allowed opacity-60" : "hover:bg-surface-hover"
            }`}
            data-item={item.id}
            data-disabled={item.disabled ? "true" : undefined}
          >
            <span className="font-medium text-foreground">{item.label}</span>
            <span className="text-2xs text-text-secondary">{item.disabled ?? item.detail}</span>
          </button>
        ))
      ) : (
        <p className="px-2 py-1.5 text-text-secondary" data-testid="chart-menu-signed-out">
          <Link
            href={signInHref}
            className="text-foreground underline underline-offset-2"
            role="menuitem"
          >
            Sign in to set alerts and plan trades
          </Link>{" "}
          from the chart.
        </p>
      )}
      <p
        className="border-t border-border-muted px-2 pt-1.5 pb-1 text-2xs leading-4 text-text-tertiary"
        data-testid="chart-menu-note"
      >
        {note}
      </p>
    </div>
  );
}

export type PlanEditorValues = PlanPrefill & { size: string; why: string };

/**
 * "Plan a trade here": the A5.4 plan fields for a long plan, filled from the
 * chart. The figures and their first problem come from `planFigures`, the
 * same check the ticket and the Journal's editor run; the API checks again.
 */
export function ChartPlanEditor({
  ticker,
  initial,
  onSave,
  onClose,
}: {
  ticker: string;
  initial: PlanEditorValues;
  onSave: (values: PlanEditorValues) => Promise<string | null>;
  onClose: () => void;
}) {
  const id = useId();
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const figures = planFigures(values);
  const set = (patch: Partial<PlanEditorValues>) => setValues((v) => ({ ...v, ...patch }));
  const firstRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    firstRef.current?.focus();
  }, []);
  const stopNote =
    initial.stopFrom === "drawing"
      ? "Stop from the nearest drawing below."
      : initial.stopFrom === "atr"
        ? "Stop 2 × ATR(14) below the entry."
        : "";
  const targetNote =
    initial.targetFrom === "drawing"
      ? "Target from the nearest drawing above."
      : initial.targetFrom === "2r"
        ? "Target at 2R."
        : "";

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="rounded-md border border-border bg-surface-elevated p-3 text-xs shadow-lg"
      data-testid="chart-plan-editor"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 id={`${id}-title`} className="text-sm font-semibold">
          Plan a Trade: {ticker}
        </h3>
        <span className="text-2xs text-text-tertiary">Long, in your default book</span>
      </div>
      <form
        className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (figures.problem) {
            setError(figures.problem);
            return;
          }
          setBusy(true);
          void onSave(values).then((problem) => {
            setBusy(false);
            setError(problem);
          });
        }}
      >
        {(
          [
            ["entry", "Entry"],
            ["stop", "Stop"],
            ["target", "Target"],
            ["size", "Size"],
          ] as const
        ).map(([name, label], i) => (
          <div key={name} className="space-y-1">
            <Label htmlFor={`${id}-${name}`} className="text-2xs">
              {label}
            </Label>
            <Input
              ref={i === 0 ? firstRef : undefined}
              id={`${id}-${name}`}
              name={name}
              inputMode="decimal"
              value={values[name]}
              onChange={(event) => set({ [name]: event.target.value })}
              className="h-8 text-xs"
            />
          </div>
        ))}
        <div className="col-span-2 space-y-1 sm:col-span-4">
          <Label htmlFor={`${id}-why`} className="text-2xs">
            Why
          </Label>
          <Input
            id={`${id}-why`}
            name="why"
            value={values.why}
            maxLength={2000}
            onChange={(event) => set({ why: event.target.value })}
            className="h-8 text-xs"
          />
        </div>
        <p className="col-span-2 text-2xs text-text-tertiary sm:col-span-4">
          {[stopNote, targetNote].filter(Boolean).join(" ")}
          {figures.rewardRisk !== null ? ` R:R ${figures.rewardRisk.toFixed(2)}.` : ""}
          {figures.risk !== null ? ` Risk ${figures.risk.toFixed(2)}.` : ""} A draft&apos;s lines
          can be dragged on the chart until its first fill locks it.
        </p>
        {error ? (
          <p className="col-span-2 text-2xs text-negative sm:col-span-4" role="alert">
            {error}
          </p>
        ) : null}
        <div className="col-span-2 flex gap-2 sm:col-span-4">
          <Button type="submit" size="sm" disabled={busy}>
            Save Plan
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}
