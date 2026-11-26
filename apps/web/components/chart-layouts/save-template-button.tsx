"use client";

/**
 * A6.8: "Save as template" on the stock page. Saves the chart's type, scale
 * and indicators, with the pane heights the chart remembers in this browser
 * (`readPaneLayout`), as a chart template for the chart workspace.
 */

import Link from "next/link";
import { useId, useState, useTransition } from "react";

import { createTemplateAction } from "@/app/(product)/(authed)/charts/actions";
import { Button } from "@/components/ui/button";
import { readPaneLayout } from "@/lib/chart-panes";
import type { ChartScale, ChartType } from "@/lib/chart-view";

const MIN_HEIGHT = 48;
const MAX_HEIGHT = 1200;

/** The remembered heights the API accepts (whole pixels, 48 to 1200). */
export function templateHeights(heights: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [kind, value] of Object.entries(heights)) {
    const px = Math.round(value);
    if (/^[a-z][a-z0-9_]{0,31}$/.test(kind) && px >= MIN_HEIGHT && px <= MAX_HEIGHT) out[kind] = px;
  }
  return out;
}

export function SaveTemplateButton({
  chartType,
  scale,
  indicators,
}: {
  chartType: ChartType;
  scale: ChartScale;
  indicators: string[];
}) {
  const formId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, startSaving] = useTransition();
  const [result, setResult] = useState<{ error?: string; saved?: string } | null>(null);

  return (
    <div className="flex flex-wrap items-center gap-2 px-1 pt-1 text-xs">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-expanded={open}
        aria-controls={formId}
        onClick={() => setOpen((v) => !v)}
        data-testid="save-template-toggle"
      >
        Save as template
      </Button>
      {open ? (
        <form
          id={formId}
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const cleaned = name.trim();
            if (!cleaned) {
              setResult({ error: "Name the template first." });
              return;
            }
            startSaving(async () => {
              const out = await createTemplateAction({
                name: cleaned,
                chart_type: chartType,
                scale,
                indicators,
                pane_heights: templateHeights(readPaneLayout().heights),
              });
              setResult(out.error ? { error: out.error } : { saved: cleaned });
              if (!out.error) setName("");
            });
          }}
        >
          <label className="inline-flex items-center gap-1.5 text-text-secondary">
            Template name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={64}
              className="h-8 w-40 rounded-md border border-input bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60"
              data-testid="save-template-name"
            />
          </label>
          <Button type="submit" size="sm" disabled={saving} data-testid="save-template-submit">
            Save
          </Button>
        </form>
      ) : null}
      {result?.error ? (
        <p role="alert" className="text-negative">
          {result.error}
        </p>
      ) : result?.saved ? (
        <p className="text-text-secondary" data-testid="save-template-saved">
          Saved {result.saved}.{" "}
          <Link href="/charts" className="underline hover:text-foreground">
            Open the chart workspace
          </Link>
        </p>
      ) : null}
    </div>
  );
}
